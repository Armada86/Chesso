import random
import chess
import db
from chess_ai import choose_move, LEVELS


def test_levels_return_legal_moves():
    b = chess.Board()
    for lvl in LEVELS:
        assert choose_move(b, lvl, random.Random(1)) in b.legal_moves


def test_finds_mate_in_one():
    b = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")  # Ra8#
    for lvl in ("Medium", "Hard"):
        assert choose_move(b, lvl, random.Random(0)).uci() == "a1a8"


def test_db_roundtrip(tmp_path):
    eng = db.make_engine(f"sqlite:///{tmp_path/'t.db'}")
    b = chess.Board()
    for m in ("e2e4", "e7e5", "g1f3"):
        b.push_uci(m)
    pgn = db.board_to_pgn(b, white="A", black="B")
    gid = db.save_game(eng, mode="training", title="t", pgn=pgn)
    g = db.get_game(eng, gid)
    sans, boards, _ = db.pgn_to_positions(g["pgn"])
    assert sans == ["e4", "e5", "Nf3"] and boards[-1].fen() == b.fen()
    assert len(db.list_games(eng, "training")) == 1
    db.delete_game(eng, gid)
    assert db.list_games(eng) == []
