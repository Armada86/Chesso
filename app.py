"""Chesso - a Streamlit chess app: play the AI (3 levels) or record training games."""
from __future__ import annotations

import chess
import streamlit as st

import db
from board_component import chess_board
from chess_ai import LEVELS, choose_move

st.set_page_config(page_title="Chesso", page_icon="♞", layout="wide")


@st.cache_resource
def get_engine():
    url, is_neon = db.get_database_url()
    return db.make_engine(url), is_neon


def san_table(board_or_sans):
    sans = board_or_sans
    rows = []
    for i in range(0, len(sans), 2):
        rows.append(f"{i // 2 + 1}. {sans[i]}" + (f"  {sans[i + 1]}" if i + 1 < len(sans) else ""))
    return "\n".join(rows)


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
        live = not game_over(board) and not ss.ai_resigned and board.turn == human
        mv = chess_board(board, key="ai_board_ui", flipped=(human == chess.BLACK), interactive=live)
        if mv:
            board.push(mv)
            st.rerun()
    with right:
        st.subheader(f"You vs AI - {ss.ai_level}")
        st.info(status_text(board))
        if not game_over(board) and not ss.ai_resigned:
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
        mv = chess_board(board, key="tr_board_ui", flipped=ss.get("tr_flip", False),
                         interactive=not game_over(board))
        if mv:
            board.push(mv)
            ss.tr_redo = []
            st.rerun()
    with right:
        st.subheader("Training - play both sides")
        st.info(status_text(board))
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
    with st.sidebar:
        st.caption("Saved games")
        f = st.radio("Show", ["All", "Training", "Vs AI"], horizontal=True, key="lib_filter")
        mode = {"All": None, "Training": "training", "Vs AI": "vs_ai"}[f]
        rows = db.list_games(engine, mode)
        if not rows:
            st.write("No saved games yet.")
        ids = [r["id"] for r in rows]
        if ss.get("lib_gid") not in ids:
            ss.lib_gid = ids[0] if ids else None
        with st.container(height=320, border=False):
            for r in rows:
                label = f"#{r['id']} {r['title']} · {r['created_at']:%b %d}"
                if st.button(label, key=f"game_{r['id']}", use_container_width=True,
                             type="primary" if r["id"] == ss.lib_gid else "secondary"):
                    ss.lib_gid = r["id"]
                    st.rerun()
    gid = ss.lib_gid
    if gid is None:
        st.info("No saved games to show. Save one from Training mode or finish a game vs the AI.")
        return
    game = db.get_game(engine, gid)
    sans, boards, _ = db.pgn_to_positions(game["pgn"])
    key = f"slider_{gid}"            # single source of truth for the current move
    last = len(sans)
    ss.setdefault(key, last)

    def go(to: int):                 # runs before the rerun, so the slider picks it up
        ss[key] = max(0, min(last, to))

    left, right = st.columns([3, 2])
    with right:
        st.caption(f"Result: {game['result']}" + (f" - AI level: {game['level']}" if game["level"] else ""))
        if last:
            st.slider("Move", 0, last, key=key)
        with st.container(horizontal=True):
            st.button("⏮", key="nav_first", on_click=go, args=(0,))
            st.button("◀", key="nav_prev", on_click=go, args=(ss[key] - 1,))
            st.button("▶", key="nav_next", on_click=go, args=(ss[key] + 1,))
            st.button("⏭", key="nav_last", on_click=go, args=(last,))
        st.code(san_table(sans) or "No moves", language=None)
        st.download_button("Download PGN", game["pgn"], file_name=f"chesso_{gid}.pgn")
        if st.button("Delete game", type="secondary"):
            db.delete_game(engine, gid)
            ss.pop(key, None)
            st.rerun()
    with left:
        chess_board(boards[ss[key]], key="lib_board_ui", interactive=False)


# --------------------------------------------------------------------------------- main
def main():
    st.title("♞ Chesso")
    engine, is_neon = get_engine()
    if not is_neon:
        st.sidebar.warning("No DATABASE_URL set - using a local SQLite file. "
                           "Set your Neon URL to persist games in the cloud.")
    pages = {"Play vs AI": page_vs_ai, "Training mode": page_training, "Saved games": page_library}
    st.session_state.setdefault("page", "Play vs AI")
    for name in pages:
        active = st.session_state.page == name
        if st.sidebar.button(name, key=f"nav_{name}", use_container_width=True,
                             type="primary" if active else "secondary"):
            st.session_state.page = name
            st.rerun()
    st.sidebar.divider()
    pages[st.session_state.page](engine)


main()
