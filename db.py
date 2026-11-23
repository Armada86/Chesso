"""Persistence layer. Neon (Postgres) via DATABASE_URL; SQLite fallback for local dev."""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone

import chess
import chess.pgn
from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table, Text,
                        create_engine, delete, insert, select)
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
    # SQLAlchemy wants the 'postgresql://' scheme (Heroku-style 'postgres://' is rejected).
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url, True


def make_engine(url: str | None = None) -> Engine:
    url = url or get_database_url()[0]
    # pool_pre_ping: Neon suspends idle compute; reconnect transparently.
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300)
    metadata.create_all(engine)
    return engine


def board_to_pgn(board: chess.Board, *, white="White", black="Black",
                 result: str | None = None, start_fen: str | None = None) -> str:
    """Serialize a board's move stack to PGN."""
    game = chess.pgn.Game()
    base = chess.Board(start_fen) if start_fen else chess.Board()
    if start_fen:
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
              level: str | None = None, human_color: str | None = None) -> int:
    with engine.begin() as conn:
        res = conn.execute(insert(games).values(
            mode=mode, title=title.strip() or "Untitled", level=level,
            human_color=human_color, result=result, pgn=pgn,
            created_at=datetime.now(timezone.utc),
        ))
        return int(res.inserted_primary_key[0])


def list_games(engine: Engine, mode: str | None = None):
    q = select(games).order_by(games.c.created_at.desc())
    if mode:
        q = q.where(games.c.mode == mode)
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
