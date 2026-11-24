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


def test_normalize_url():
    for u in ("postgres://u:p@h/d?sslmode=require", "postgresql+psycopg://u:p@h/d?sslmode=require",
              " 'postgresql://u:p@h/d?sslmode=require' ", "psql 'postgresql://u:p@h/d?sslmode=require'"):
        assert db.normalize_url(u) == "postgresql+psycopg2://u:p@h/d?sslmode=require"
    assert db.normalize_url("sqlite:///x.db") == "sqlite:///x.db"


def test_in_progress_vs_finished(tmp_path):
    eng = db.make_engine(f"sqlite:///{tmp_path/'s.db'}")
    gid = db.save_game(eng, mode="vs_ai", title="wip", pgn="1. e4 *", level="Easy",
                       human_color="white", status="in_progress")
    # in-progress games are kept out of the Saved games library
    assert db.list_games(eng) == []
    assert [g["id"] for g in db.list_in_progress(eng)] == [gid]
    db.update_game(eng, gid, pgn="1. e4 e5 1-0", result="1-0", status="finished")
    assert db.list_in_progress(eng) == []
    assert [g["id"] for g in db.list_games(eng)] == [gid]
    assert db.get_game(eng, gid)["result"] == "1-0"


def test_migrates_old_table(tmp_path):
    from sqlalchemy import create_engine, text
    url = f"sqlite:///{tmp_path/'old.db'}"
    old = create_engine(url)
    with old.begin() as c:  # the original schema, before status/updated_at existed
        c.execute(text("CREATE TABLE games (id INTEGER PRIMARY KEY AUTOINCREMENT, mode VARCHAR(16) NOT NULL,"
                       " title VARCHAR(200) NOT NULL, level VARCHAR(16), human_color VARCHAR(5),"
                       " result VARCHAR(10) NOT NULL, pgn TEXT NOT NULL, created_at TIMESTAMP NOT NULL)"))
        c.execute(text("INSERT INTO games (mode,title,result,pgn,created_at) "
                       "VALUES ('training','old','*','1. e4 *','2026-01-01')"))
    eng = db.make_engine(url)
    rows = db.list_games(eng)           # old rows count as finished
    assert len(rows) == 1 and rows[0]["status"] == "finished"
    db.make_engine(url)                  # running twice is harmless


def test_captured_pieces_and_lead():
    from captures import captured_pieces, material_lead
    b = chess.Board()
    for m in ("e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5a5"):   # Qxd5 ... Qa5
        b.push_uci(m)
    caps = captured_pieces(b)
    assert [p.symbol() for p in caps[chess.WHITE]] == ["p"]      # white took a black pawn
    assert [p.symbol() for p in caps[chess.BLACK]] == ["P"]
    assert material_lead(b) == 0


def test_en_passant_counts_as_pawn_capture():
    from captures import captured_pieces
    b = chess.Board()
    for m in ("e2e4", "a7a6", "e4e5", "d7d5", "e5d6"):           # exd6 e.p.
        b.push_uci(m)
    assert [p.symbol() for p in captured_pieces(b)[chess.WHITE]] == ["p"]


def test_openings_are_valid_and_seeded_once(tmp_path):
    import openings
    assert len(openings.OPENINGS) == 10
    assert len({o.name for o in openings.OPENINGS}) == 10
    for op in openings.OPENINGS:
        board = chess.Board()
        for san in op.moves.split():
            board.push_san(san)                      # raises if any move is illegal
        assert op.notes and max(op.notes) <= len(op.moves.split())
        info = db.pgn_info(openings.build_pgn(op))   # round-trips through PGN
        assert info["intro"] == op.idea
        for ply, text in op.notes.items():
            assert info["notes"][ply - 1] == text
    eng = db.make_engine(f"sqlite:///{tmp_path/'o.db'}")
    assert openings.seed(eng) == 10
    assert openings.seed(eng) == 0                   # idempotent
    assert len(db.list_games(eng, mode="opening", status=None)) == 10


# ---------------------------------------------------------------- Make mode: position checks
def _problems(fen, turn=None):
    from position_check import validate_position
    b = chess.Board(fen)
    if turn is not None:
        b.turn = turn
    return validate_position(b)


def test_standard_and_legal_custom_positions_pass():
    assert _problems(chess.STARTING_FEN) == []
    assert _problems("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1") == []
    assert _problems("rnbqkbnr/pppppppp/8/8/8/8/PPPPPP2/RNBBKBBR w - - 0 1") == []   # 2 promotions available


def test_kings_required():
    p = _problems("8/8/8/8/8/8/8/8 w - - 0 1")
    assert any("White must have exactly one king" in m for m in p)
    assert any("Black must have exactly one king" in m for m in p)
    p = _problems("kk6/8/8/8/8/8/8/4K3 w - - 0 1")
    assert any("Black must have exactly one king (found 2)" in m for m in p)


def test_two_bishops_on_same_colour_needs_a_promotion():
    # d1 and f1 are both light squares; with all 8 pawns that is impossible
    p = _problems("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBBKBNR w - - 0 1")
    assert len(p) == 1 and "2 bishops on light squares" in p[0] and "all 8 pawns" in p[0]
    # one pawn missing makes a promoted bishop possible
    assert _problems("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP1/RNBBKBNR w - - 0 1") == []
    # one light + one dark bishop is the normal pair
    assert _problems("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RN1QKBNR w - - 0 1") == []


def test_extra_pieces_need_missing_pawns():
    assert any("2 queens" in m for m in _problems("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBQR w - - 0 1"))
    assert any("3 knights" in m for m in _problems("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKNNR w - - 0 1"))
    # 2 extra pieces, only 1 pawn missing
    p = _problems("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP1/RNBQKBQQ w - - 0 1")
    assert any("1 White pawn is missing and 2 would be needed" in m for m in p)


def test_pawn_rules():
    assert any("9 pawns" in m for m in _problems("4k3/pppppppp/p7/8/8/8/PPPPPPPP/4K3 w - - 0 1"))
    assert any("first or last rank (a8)" in m for m in _problems("P3k3/8/8/8/8/8/8/4K3 w - - 0 1"))
    assert any("first or last rank (h1)" in m for m in _problems("4k3/8/8/8/8/8/8/4K2p w - - 0 1"))


def test_check_and_game_over_rules():
    assert any("touching" in m for m in _problems("8/8/8/3kK3/8/8/8/8 w - - 0 1"))
    # Black is in check but White is to move
    assert any("Black's king is in check, but it is White's turn" in m
               for m in _problems("4k3/8/8/8/8/8/8/4RK2 w - - 0 1"))
    # same position with Black to move is a normal position
    assert _problems("4k3/8/8/8/8/8/8/4RK2 b - - 0 1") == []
    assert any("checkmated" in m for m in _problems("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"))
    assert any("stalemate" in m for m in _problems("7k/5Q2/8/8/8/8/8/6K1 b - - 0 1"))
    assert any("enough pieces" in m for m in _problems("4k3/8/8/8/8/8/8/4K3 w - - 0 1"))


def test_custom_start_position_round_trips_through_pgn():
    start = chess.Board("4k3/4p3/8/8/8/8/4P3/R3K3 b - - 0 1")     # Black moves first
    b = start.copy()
    for uci in ("e7e5", "e2e4", "e8e7"):
        b.push_uci(uci)
    pgn = db.board_to_pgn(b, white="A", black="B", result="*")
    assert '[FEN "4k3/4p3/8/8/8/8/4P3/R3K3 b - - 0 1"]' in pgn
    sans, boards, _ = db.pgn_to_positions(pgn)
    assert sans == ["e5", "e4", "Ke7"] and boards[-1].fen() == b.fen()
    assert boards[-1].root().fen() == start.fen()                  # the custom start survives loading


def test_captures_use_the_custom_start_not_the_standard_one():
    from captures import captured_pieces
    b = chess.Board("4k3/8/8/3p4/4P3/8/8/R3K3 w - - 0 1")          # white pawn e4, black pawn d5
    b.push_uci("e4d5")                                             # exd5
    caps = captured_pieces(b)
    assert [p.symbol() for p in caps[chess.WHITE]] == ["p"] and caps[chess.BLACK] == []


def test_positions_save_and_load_even_when_illegal(tmp_path):
    eng = db.make_engine(f"sqlite:///{tmp_path/'p.db'}")
    for fen in ("8/8/8/8/8/8/8/8 w - - 0 1",                          # empty board
                "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1",               # Black to move, castling on
                "4k3/8/8/8/8/8/8/4KQQ1 w - - 0 1"):
        pgn = db.board_to_pgn(chess.Board(fen), white="White", black="Black", result="*")
        gid = db.save_game(eng, mode="position", title="p", pgn=pgn)
        _, boards, _ = db.pgn_to_positions(db.get_game(eng, gid)["pgn"])
        assert boards[0].fen() == chess.Board(fen).fen()
    assert len(db.list_games(eng, mode="position", status=None)) == 3
    assert db.list_games(eng, mode="training", status=None) == []     # kept apart from the other lists
