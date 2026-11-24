"""Persistence layer. Neon (Postgres) via DATABASE_URL; SQLite fallback for local dev."""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone

import chess
import chess.pgn
from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table, Text,
                        create_engine, delete, inspect, insert, select, text, update)
from sqlalchemy.engine import Engine

metadata = MetaData()

games = Table(
    "games", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("mode", String(16), nullable=False),        # 'training' | 'vs_ai'
    Column("title", String(200), nullable=False),
    Column("level", String(16)),                       # AI level for vs_ai games
    Column("human_color", String(5)),                  # 'white' | 'black' for vs_ai
    Column("result", String(10), nullable=False, default="*"),
    Column("pgn", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # 'finished' = shows up in Saved games; 'in_progress' = a Play-vs-AI game you can resume.
    Column("status", String(16), nullable=False, default="finished", server_default="finished"),
    Column("updated_at", DateTime(timezone=True)),
)

LOCAL_FALLBACK = "sqlite:///chesso_local.db"


def get_database_url() -> tuple[str, bool]:
    """Return (url, is_neon). Looks at Streamlit secrets, then the environment."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            import streamlit as st
            url = st.secrets.get("DATABASE_URL")
        except Exception:
            url = None
    if not url:
        return LOCAL_FALLBACK, False
    return normalize_url(url), True


def normalize_url(url: str) -> str:
    """Force Postgres URLs onto the psycopg2 driver we install.

    Accepts 'postgres://', 'postgresql://', or 'postgresql+<anything>://'
    and tolerates stray whitespace/quotes from copy-pasting.
    """
    url = url.strip().strip("'\"")
    if url.startswith("psql "):
        url = url[5:].strip().strip("'\"")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    if url.startswith("postgresql+"):
        return "postgresql+psycopg2://" + url.split("://", 1)[1]
    return url


def make_engine(url: str | None = None) -> Engine:
    url = url or get_database_url()[0]
    # pool_pre_ping: Neon suspends idle compute; reconnect transparently.
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    metadata.create_all(engine)
    _migrate(engine)
    return engine


def _migrate(engine: Engine) -> None:
    """Add columns introduced after the first release to an existing table."""
    have = {c["name"] for c in inspect(engine).get_columns("games")}
    with engine.begin() as conn:
        if "status" not in have:
            conn.execute(text("ALTER TABLE games ADD COLUMN status VARCHAR(16) "
                              "NOT NULL DEFAULT 'finished'"))
        if "updated_at" not in have:
            conn.execute(text("ALTER TABLE games ADD COLUMN updated_at TIMESTAMP"))
        # Earlier versions put "Make mode" into the saved names; the lists now group by mode instead.
        conn.execute(text("UPDATE games SET title = REPLACE(title, ' · Make mode', '') "
                          "WHERE title LIKE '% · Make mode%'"))
        conn.execute(text("UPDATE games SET title = 'Custom position' WHERE title = 'Make mode position'"))


def board_to_pgn(board: chess.Board, *, white="White", black="Black",
                 result: str | None = None, start_fen: str | None = None) -> str:
    """Serialize a board's move stack to PGN."""
    game = chess.pgn.Game()
    base = chess.Board(start_fen) if start_fen else board.root()   # custom start positions keep their FEN
    if base.fen() != chess.STARTING_FEN:
        game.setup(base)
    game.headers["White"], game.headers["Black"] = white, black
    node = game
    replay = base.copy()
    for mv in board.move_stack:
        node = node.add_variation(mv)
        replay.push(mv)
    if result is None:
        result = board.result(claim_draw=True)  # "*" while the game is in progress
    game.headers["Result"] = result
    return str(game)


def save_game(engine: Engine, *, mode: str, title: str, pgn: str, result: str = "*",
              level: str | None = None, human_color: str | None = None,
              status: str = "finished") -> int:
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        res = conn.execute(insert(games).values(
            mode=mode, title=title.strip() or "Untitled", level=level,
            human_color=human_color, result=result, pgn=pgn, status=status,
            created_at=now, updated_at=now,
        ))
        return int(res.inserted_primary_key[0])


def update_game(engine: Engine, game_id: int, *, pgn: str, result: str = "*",
                status: str = "finished", title: str | None = None) -> None:
    values = dict(pgn=pgn, result=result, status=status, updated_at=datetime.now(timezone.utc))
    if title is not None:
        values["title"] = title.strip() or "Untitled"
    with engine.begin() as conn:
        conn.execute(update(games).where(games.c.id == game_id).values(**values))


def list_games(engine: Engine, mode: str | None = None, status: str | None = "finished"):
    """List games newest-first. status=None returns every status."""
    q = select(games).order_by(games.c.created_at.desc(), games.c.id.desc())
    if mode:
        q = q.where(games.c.mode == mode)
    if status:
        q = q.where(games.c.status == status)
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]


def list_in_progress(engine: Engine):
    """Play-vs-AI games that were saved mid-game, most recently saved first."""
    q = (select(games).where(games.c.mode == "vs_ai", games.c.status == "in_progress")
         .order_by(games.c.updated_at.desc(), games.c.id.desc()))
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]


def get_game(engine: Engine, game_id: int):
    with engine.connect() as conn:
        row = conn.execute(select(games).where(games.c.id == game_id)).first()
    return dict(row._mapping) if row else None


def delete_game(engine: Engine, game_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(delete(games).where(games.c.id == game_id))


def pgn_to_positions(pgn: str):
    """Parse PGN -> (list of SAN moves, list of boards after each ply incl. start)."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    board = game.board()
    sans, boards, moves = [], [board.copy()], []
    for mv in game.mainline_moves():
        sans.append(board.san(mv))
        board.push(mv)
        moves.append(mv)
        boards.append(board.copy())
    return sans, boards, moves


def pgn_info(pgn: str) -> dict:
    """Headers plus comments: {'headers': {...}, 'intro': str, 'notes': [comment per ply]}."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    return {"headers": dict(game.headers), "intro": game.comment.strip(),
            "notes": [n.comment.strip() for n in game.mainline()]}
