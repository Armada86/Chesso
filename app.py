"""Chesso - a Streamlit chess app: play the AI (3 levels) or record training games."""
from __future__ import annotations

import chess
import chess.svg
import streamlit as st

import db
from chess_ai import LEVELS, choose_move

st.set_page_config(page_title="Chesso", page_icon="♞", layout="wide")


@st.cache_resource
def get_engine():
    url, is_neon = db.get_database_url()
    return db.make_engine(url), is_neon


def board_svg(board: chess.Board, *, flipped=False, size=520, highlight=None):
    last = board.peek() if board.move_stack else None
    svg = chess.svg.board(
        board, size=size, orientation=chess.BLACK if flipped else chess.WHITE,
        lastmove=last, check=board.king(board.turn) if board.is_check() else None,
        squares=highlight or None,
    )
    st.markdown(f'<div style="text-align:center">{svg}</div>', unsafe_allow_html=True)


def san_table(board_or_sans):
    sans = board_or_sans
    rows = []
    for i in range(0, len(sans), 2):
        rows.append(f"{i // 2 + 1}. {sans[i]}" + (f"  {sans[i + 1]}" if i + 1 < len(sans) else ""))
    return "\n".join(rows)


def move_input(board: chess.Board, key: str):
    """From/To picker. Returns a chess.Move when submitted, else None."""
    legal = list(board.legal_moves)
    froms = sorted({m.from_square for m in legal})
    with st.form(f"move_form_{key}", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        src = c1.selectbox("From", [chess.square_name(s) for s in froms], key=f"from_{key}")
        tos = sorted({m.to_square for m in legal if chess.square_name(m.from_square) == src})
        dst = c2.selectbox("To", [chess.square_name(s) for s in tos], key=f"to_{key}")
        promo = c3.selectbox("Promote to", ["Queen", "Rook", "Bishop", "Knight"], key=f"pr_{key}")
        go = st.form_submit_button("Make move", type="primary", use_container_width=True)
    if not go:
        return None
    frm, to = chess.parse_square(src), chess.parse_square(dst)
    pt = {"Queen": chess.QUEEN, "Rook": chess.ROOK, "Bishop": chess.BISHOP,
          "Knight": chess.KNIGHT}[promo]
    for cand in (chess.Move(frm, to), chess.Move(frm, to, promotion=pt)):
        if cand in board.legal_moves:
            return cand
    st.warning("That move isn't legal from the selected squares. Pick another 'To' square.")
    return None


def status_text(board: chess.Board) -> str:
    if board.is_checkmate():
        return f"Checkmate - {'Black' if board.turn == chess.WHITE else 'White'} wins!"
    if board.is_stalemate():
        return "Draw by stalemate."
    if board.is_insufficient_material():
        return "Draw - insufficient material."
    if board.can_claim_draw():
        return "Draw can be claimed (repetition / 50-move rule)."
    side = "White" if board.turn == chess.WHITE else "Black"
    return f"{side} to move" + (" - check!" if board.is_check() else "")


def game_over(board: chess.Board) -> bool:
    return board.is_game_over(claim_draw=True)


# --------------------------------------------------------------------------- AI mode
def page_vs_ai(engine):
    ss = st.session_state
    if "ai_board" not in ss:
        ss.ai_board = chess.Board()
        ss.ai_level, ss.ai_color = "Medium", "white"
        ss.ai_saved = False
        ss.ai_resigned = False

    with st.sidebar:
        st.subheader("New game")
        level = st.radio("AI level", list(LEVELS), index=list(LEVELS).index(ss.ai_level))
        color = st.radio("Play as", ["white", "black"], index=["white", "black"].index(ss.ai_color))
        if st.button("Start new game", use_container_width=True):
            ss.ai_board, ss.ai_level, ss.ai_color, ss.ai_saved = chess.Board(), level, color, False
            ss.ai_resigned = False
            st.rerun()

    board: chess.Board = ss.ai_board
    human = chess.WHITE if ss.ai_color == "white" else chess.BLACK

    # AI moves automatically when it's its turn.
    if not game_over(board) and not ss.ai_resigned and board.turn != human:
        with st.spinner(f"AI ({ss.ai_level}) is thinking..."):
            board.push(choose_move(board, ss.ai_level))
        st.rerun()

    left, right = st.columns([3, 2])
    with left:
        board_svg(board, flipped=(human == chess.BLACK))
    with right:
        st.subheader(f"You vs AI - {ss.ai_level}")
        st.info(status_text(board))
        if not game_over(board) and not ss.ai_resigned:
            mv = move_input(board, "ai")
            if mv:
                board.push(mv)
                st.rerun()
            if st.button("Resign", use_container_width=True):
                ss.ai_resigned = True
                st.rerun()
        sans = _sans(board)
        st.code(san_table(sans) or "No moves yet", language=None)
        _save_ai_game(engine, board, human)


def _sans(board: chess.Board):
    tmp, out = chess.Board(), []
    for m in board.move_stack:
        out.append(tmp.san(m))
        tmp.push(m)
    return out


def _save_ai_game(engine, board, human):
    ss = st.session_state
    resigned = ss.ai_resigned
    if not (game_over(board) or resigned) or ss.ai_saved:
        return
    result = ("0-1" if human == chess.WHITE else "1-0") if resigned else board.result(claim_draw=True)
    me, ai = "You", f"AI ({ss.ai_level})"
    white, black = (me, ai) if human == chess.WHITE else (ai, me)
    pgn = db.board_to_pgn(board, white=white, black=black, result=result)
    gid = db.save_game(engine, mode="vs_ai", title=f"{white} vs {black}", pgn=pgn,
                       result=result, level=ss.ai_level, human_color=ss.ai_color)
    ss.ai_saved = True
    st.success(f"Game over ({result}). Saved to your library as #{gid}.")


# ----------------------------------------------------------------------- Training mode
def page_training(engine):
    ss = st.session_state
    if "tr_board" not in ss:
        ss.tr_board, ss.tr_redo = chess.Board(), []

    board: chess.Board = ss.tr_board
    left, right = st.columns([3, 2])
    with left:
        board_svg(board, flipped=ss.get("tr_flip", False))
    with right:
        st.subheader("Training - play both sides")
        st.info(status_text(board))
        if not game_over(board):
            mv = move_input(board, "tr")
            if mv:
                board.push(mv)
                ss.tr_redo = []
                st.rerun()
        c1, c2, c3 = st.columns(3)
        if c1.button("Undo", disabled=not board.move_stack, use_container_width=True):
            ss.tr_redo.append(board.pop())
            st.rerun()
        if c2.button("Redo", disabled=not ss.tr_redo, use_container_width=True):
            board.push(ss.tr_redo.pop())
            st.rerun()
        if c3.button("Flip", use_container_width=True):
            ss.tr_flip = not ss.get("tr_flip", False)
            st.rerun()
        st.code(san_table(_sans(board)) or "No moves yet", language=None)

        with st.form("save_training", clear_on_submit=False):
            title = st.text_input("Title", placeholder="e.g. Italian Game ideas")
            save = st.form_submit_button("Save this line", type="primary",
                                         use_container_width=True, disabled=not board.move_stack)
        if save:
            pgn = db.board_to_pgn(board, white="Training", black="Training")
            gid = db.save_game(engine, mode="training", title=title or "Untitled line",
                               pgn=pgn, result=board.result(claim_draw=True))
            st.success(f"Saved as #{gid}. Find it under 'Saved games'.")
        if st.button("Clear board", use_container_width=True):
            ss.tr_board, ss.tr_redo = chess.Board(), []
            st.rerun()


# ------------------------------------------------------------------------ Saved games
def page_library(engine):
    ss = st.session_state
    f = st.radio("Show", ["All", "Training", "Vs AI"], horizontal=True)
    mode = {"All": None, "Training": "training", "Vs AI": "vs_ai"}[f]
    rows = db.list_games(engine, mode)
    if not rows:
        st.write("No saved games yet.")
        return
    labels = {r["id"]: f"#{r['id']} - {r['title']} [{r['mode']}] {r['created_at']:%Y-%m-%d %H:%M}"
              for r in rows}
    gid = st.selectbox("Game", list(labels), format_func=labels.get)
    game = db.get_game(engine, gid)
    sans, boards, _ = db.pgn_to_positions(game["pgn"])
    key = f"ply_{gid}"
    ss.setdefault(key, len(sans))
    left, right = st.columns([3, 2])
    with right:
        st.caption(f"Result: {game['result']}" + (f" - AI level: {game['level']}" if game["level"] else ""))
        ss[key] = st.slider("Move", 0, len(sans), ss[key], key=f"slider_{gid}")
        b1, b2, b3, b4 = st.columns(4)
        if b1.button("⏮", key="first"): ss[key] = 0; st.rerun()
        if b2.button("◀", key="prev"): ss[key] = max(0, ss[key] - 1); st.rerun()
        if b3.button("▶", key="next"): ss[key] = min(len(sans), ss[key] + 1); st.rerun()
        if b4.button("⏭", key="last"): ss[key] = len(sans); st.rerun()
        st.code(san_table(sans) or "No moves", language=None)
        st.download_button("Download PGN", game["pgn"], file_name=f"chesso_{gid}.pgn")
        if st.button("Delete game", type="secondary"):
            db.delete_game(engine, gid)
            ss.pop(key, None)
            st.rerun()
    with left:
        board_svg(boards[ss[key]])


# --------------------------------------------------------------------------------- main
def main():
    st.title("♞ Chesso")
    engine, is_neon = get_engine()
    if not is_neon:
        st.sidebar.warning("No DATABASE_URL set - using a local SQLite file. "
                           "Set your Neon URL to persist games in the cloud.")
    page = st.sidebar.radio("Mode", ["Play vs AI", "Training mode", "Saved games"])
    {"Play vs AI": page_vs_ai, "Training mode": page_training, "Saved games": page_library}[page](engine)


main()
