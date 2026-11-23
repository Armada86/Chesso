"""Chesso - a Streamlit chess app: play the AI (3 levels) or record training games."""
from __future__ import annotations

import functools
import time

import chess
import chess.svg
import streamlit as st

import db
from board_component import chess_board
from captures import captured_pieces, material_lead
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


# ------------------------------------------------------------ captured pieces display
AI_MOVE_DELAY = 1.0   # seconds the AI "waits" so you can see your own move first

@functools.lru_cache(maxsize=None)
def _mini_piece(symbol: str) -> str:
    svg = chess.svg.piece(chess.Piece.from_symbol(symbol), size=22)
    return " ".join(svg.split())          # single line so Markdown can't break the SVG


def _capture_strip(label: str, pieces: list[chess.Piece], lead: int) -> str:
    icons = "".join(_mini_piece(p.symbol()) for p in pieces)
    plus = f'<b style="margin-left:6px">+{lead}</b>' if lead > 0 else ""
    return (
        '<div style="max-width:560px;margin:2px auto;min-height:30px;display:flex;align-items:center;'
        'gap:8px;font-size:0.85rem"><span style="opacity:.75;min-width:3.2em">' + label + '</span>'
        '<span style="display:inline-flex;align-items:center;flex-wrap:wrap;background:#e9e4da;color:#333;'
        'border-radius:6px;padding:1px 6px;min-height:26px;min-width:26px">' + icons + plus + '</span></div>'
    )


def board_with_captures(board: chess.Board, *, key: str, flipped: bool, interactive: bool,
                        names: dict[bool, str]):
    """Board with a strip of captured pieces above (top player) and below (bottom player)."""
    top = chess.WHITE if flipped else chess.BLACK
    bottom = not top
    caps, lead = captured_pieces(board), material_lead(board)
    strip = lambda c: _capture_strip(names[c], caps[c], lead if c == chess.WHITE else -lead)
    st.markdown(strip(top), unsafe_allow_html=True)
    move = chess_board(board, key=key, flipped=flipped, interactive=interactive)
    st.markdown(strip(bottom), unsafe_allow_html=True)
    return move


# --------------------------------------------------------------------------- AI mode
def _sans(board: chess.Board):
    tmp, out = chess.Board(), []
    for m in board.move_stack:
        out.append(tmp.san(m))
        tmp.push(m)
    return out


def _ai_in_progress() -> bool:
    """True when there is an unfinished game with at least one move on the AI board."""
    ss = st.session_state
    b = ss.get("ai_board")
    return bool(b and b.move_stack and not game_over(b) and not ss.ai_resigned)


def _ai_players():
    ss = st.session_state
    me, ai = "You", f"AI ({ss.ai_level})"
    return (me, ai) if ss.ai_color == "white" else (ai, me)


def _ai_new_game(level: str, color: str):
    ss = st.session_state
    ss.ai_board, ss.ai_level, ss.ai_color = chess.Board(), level, color
    ss.ai_saved, ss.ai_resigned, ss.ai_game_id = False, False, None


def _ai_load_game(engine, game_id: int):
    ss = st.session_state
    row = db.get_game(engine, game_id)
    if not row:
        st.toast("That saved game no longer exists.")
        return
    _, boards, _ = db.pgn_to_positions(row["pgn"])
    ss.ai_board = boards[-1]
    ss.ai_level, ss.ai_color = row["level"] or "Medium", row["human_color"] or "white"
    ss.ai_saved, ss.ai_resigned, ss.ai_game_id = False, False, game_id


def _ai_save_in_progress(engine) -> int:
    """Save (or update) the current game as 'in progress' so it can be resumed later."""
    ss = st.session_state
    white, black = _ai_players()
    pgn = db.board_to_pgn(ss.ai_board, white=white, black=black, result="*")
    if ss.get("ai_game_id"):
        db.update_game(engine, ss.ai_game_id, pgn=pgn, result="*", status="in_progress")
    else:
        ss.ai_game_id = db.save_game(engine, mode="vs_ai", title=f"{white} vs {black}", pgn=pgn,
                                     level=ss.ai_level, human_color=ss.ai_color,
                                     status="in_progress")
    return ss.ai_game_id


def _ai_apply(engine, action):
    if action[0] == "load":
        _ai_load_game(engine, action[1])
    else:  # ("new", level, color)
        _ai_new_game(action[1], action[2])


def _ai_request(engine, action):
    """Run an action that replaces the current game; ask first if one is in progress."""
    if _ai_in_progress():
        st.session_state.confirm_action = action
    else:
        _ai_apply(engine, action)
    st.rerun()


@st.dialog("Resume a saved game")
def load_dialog(engine):
    rows = db.list_in_progress(engine)
    if not rows:
        st.write("You have no saved games in progress.")
        return
    st.caption("Games you saved while playing against the AI.")
    for r in rows:
        sans, _, _ = db.pgn_to_positions(r["pgn"])
        label = (f"{r['level']} · {r['human_color'].title()} · {len(sans)} moves · "
                 f"{(r['updated_at'] or r['created_at']):%b %d}")
        with st.container(horizontal=True, vertical_alignment="center"):
            if st.button(label, key=f"load_{r['id']}"):
                _ai_request(engine, ("load", r["id"]))
            if st.button("🗑", key=f"del_{r['id']}", help="Delete this saved game"):
                db.delete_game(engine, r["id"])
                st.session_state.show_load = True
                st.rerun()
    if st.button("Cancel", key="load_cancel"):
        st.rerun()


@st.dialog("Game in progress")
def confirm_dialog(engine, action):
    st.write("You have a game in progress. Do you want to save it before continuing?")
    if st.button("Save it, then continue", type="primary", use_container_width=True):
        _ai_save_in_progress(engine)
        _ai_apply(engine, action)
        st.rerun()
    if st.button("Don't save, just continue", use_container_width=True):
        _ai_apply(engine, action)
        st.rerun()
    if st.button("Cancel", use_container_width=True):
        st.rerun()


def page_vs_ai(engine):
    ss = st.session_state
    if "ai_board" not in ss:
        _ai_new_game("Medium", "white")

    if ss.pop("show_load", False):
        load_dialog(engine)
    action = ss.pop("confirm_action", None)
    if action:
        confirm_dialog(engine, action)

    with st.sidebar:
        st.subheader("New game")
        level = st.radio("AI level", list(LEVELS), index=list(LEVELS).index(ss.ai_level))
        color = st.radio("Play as", ["white", "black"], index=["white", "black"].index(ss.ai_color))
        if st.button("Start new game", use_container_width=True):
            _ai_request(engine, ("new", level, color))

    board: chess.Board = ss.ai_board
    human = chess.WHITE if ss.ai_color == "white" else chess.BLACK

    ai_turn = not game_over(board) and not ss.ai_resigned and board.turn != human

    left, right = st.columns([3, 2])
    with left:
        live = not game_over(board) and not ss.ai_resigned and board.turn == human
        names = {human: "You", (not human): f"AI"}
        mv = board_with_captures(board, key="ai_board_ui", flipped=(human == chess.BLACK),
                                 interactive=live, names=names)
        if mv:
            board.push(mv)
            st.rerun()
    with right:
        st.subheader(f"You vs AI - {ss.ai_level}")
        st.info(f"AI ({ss.ai_level}) is thinking..." if ai_turn else status_text(board))
        over = game_over(board) or ss.ai_resigned
        with st.container(horizontal=True):
            if st.button("💾 Save", key="ai_save", disabled=over or not board.move_stack,
                         help="Save this game so you can resume it later"):
                _ai_save_in_progress(engine)
                st.toast("Game saved. Load it any time from 'Load'.", icon="💾")
            if st.button("📂 Load", key="ai_load", help="Resume a saved game"):
                ss.show_load = True
                st.rerun()
            if st.button("Resign", key="ai_resign", disabled=over):
                ss.ai_resigned = True
                st.rerun()
        st.code(san_table(_sans(board)) or "No moves yet", language=None)
        _save_ai_game(engine, board, human)

    # The page above is already drawn (showing your move), so the pause below is visible.
    if ai_turn:
        started = time.monotonic()
        ai_move = choose_move(board, ss.ai_level)
        time.sleep(max(0.0, AI_MOVE_DELAY - (time.monotonic() - started)))
        board.push(ai_move)
        st.rerun()


def _save_ai_game(engine, board, human):
    """When the game ends (mate, draw, resign) store it as finished automatically."""
    ss = st.session_state
    if not (game_over(board) or ss.ai_resigned) or ss.ai_saved:
        return
    result = ("0-1" if human == chess.WHITE else "1-0") if ss.ai_resigned else board.result(claim_draw=True)
    white, black = _ai_players()
    pgn = db.board_to_pgn(board, white=white, black=black, result=result)
    if ss.get("ai_game_id"):   # a game that was saved mid-way: finish that record
        db.update_game(engine, ss.ai_game_id, pgn=pgn, result=result, status="finished")
        gid = ss.ai_game_id
    else:
        gid = db.save_game(engine, mode="vs_ai", title=f"{white} vs {black}", pgn=pgn,
                           result=result, level=ss.ai_level, human_color=ss.ai_color)
        ss.ai_game_id = gid
    ss.ai_saved = True
    st.success(f"Game over ({result}). Saved automatically to Saved games as #{gid}.")


# ----------------------------------------------------------------------- Training mode
def page_training(engine):
    ss = st.session_state
    if "tr_board" not in ss:
        ss.tr_board, ss.tr_redo = chess.Board(), []

    board: chess.Board = ss.tr_board
    left, right = st.columns([3, 2])
    with left:
        mv = board_with_captures(board, key="tr_board_ui", flipped=ss.get("tr_flip", False),
                                 interactive=not game_over(board),
                                 names={chess.WHITE: "White", chess.BLACK: "Black"})
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
        board_with_captures(boards[ss[key]], key="lib_board_ui", flipped=False, interactive=False,
                            names={chess.WHITE: "White", chess.BLACK: "Black"})


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
            if name == "Play vs AI" and db.list_in_progress(engine):
                st.session_state.show_load = True   # offer to resume a saved game
            st.rerun()
    if "boot_prompt" not in st.session_state:       # once when the app is first opened
        st.session_state.boot_prompt = True
        if st.session_state.page == "Play vs AI" and db.list_in_progress(engine):
            st.session_state.show_load = True
    st.sidebar.divider()
    pages[st.session_state.page](engine)


main()
