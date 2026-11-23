"""Chesso - a Streamlit chess app: play the AI (3 levels) or record training games."""
from __future__ import annotations

import functools
import time

import chess
import chess.svg
import streamlit as st

import db
import openings
from board_component import chess_board
from captures import captured_pieces, material_lead
from chess_ai import LEVELS, choose_move

st.set_page_config(page_title="Chesso", page_icon="♞", layout="wide")


@st.cache_resource
def get_engine():
    url, is_neon = db.get_database_url()
    engine = db.make_engine(url)
    openings.seed(engine)          # make sure the 10 famous openings are in the database
    return engine, is_neon


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
STRIP_GAP_TITLE = 17      # px between the title/description and the top strip
STRIP_GAP_TOP, STRIP_GAP_BOTTOM = 19.6, -8   # px; tuned so the space above and below the board is equal (~14px)
AI_MOVE_DELAY = 1.0   # seconds the AI "waits" so you can see your own move first

@functools.lru_cache(maxsize=None)
def _mini_piece(symbol: str) -> str:
    svg = chess.svg.piece(chess.Piece.from_symbol(symbol), size=20)
    return " ".join(svg.split())          # single line so Markdown can't break the SVG


def _capture_strip(label: str, pieces: list[chess.Piece], lead: int, margin: str) -> str:
    icons = "".join(_mini_piece(p.symbol()) for p in pieces)
    plus = f'<b style="margin-left:6px">+{lead}</b>' if lead > 0 else ""
    return (
        '<div style="max-width:560px;margin:' + margin + ';min-height:26px;display:flex;align-items:center;'
        'gap:8px;font-size:0.85rem"><span style="opacity:.75;min-width:3.2em">' + label + '</span>'
        '<span style="display:inline-flex;align-items:center;flex-wrap:wrap;background:#e9e4da;color:#333;'
        'border-radius:6px;padding:1px 6px;min-height:24px;min-width:24px">' + icons + plus + '</span></div>'
    )


def board_with_captures(board: chess.Board, *, key: str, flipped: bool, interactive: bool,
                        names: dict[bool, str]):
    """Board with a strip of captured pieces above (top player) and below (bottom player)."""
    top = chess.WHITE if flipped else chess.BLACK
    bottom = not top
    caps, lead = captured_pieces(board), material_lead(board)
    strip = lambda c, m: _capture_strip(names[c], caps[c], lead if c == chess.WHITE else -lead, m)
    # Explicit margins make the space between board and strip identical above and below.
    st.markdown(strip(top, f"{STRIP_GAP_TITLE}px auto {STRIP_GAP_TOP}px"), unsafe_allow_html=True)
    move = chess_board(board, key=key, flipped=flipped, interactive=interactive)
    st.markdown(strip(bottom, f"{STRIP_GAP_BOTTOM}px auto 0"), unsafe_allow_html=True)
    return move


# ------------------------------------------------------------------------ replay view
def replay_view(engine, game_id: int, *, on_close=None, extra=None):
    """Step through a game: slider, first/prev/next/last, notes, PGN download, delete.

    `extra` is an optional function that draws more buttons next to Back/Delete.
    """
    ss = st.session_state
    game = db.get_game(engine, game_id)
    if not game:
        st.info("That game no longer exists.")
        return
    is_opening = game["mode"] == "opening"
    sans, boards, _ = db.pgn_to_positions(game["pgn"])
    info = db.pgn_info(game["pgn"])
    key = f"slider_{game_id}"        # single source of truth for the current move
    last = len(sans)
    ss.setdefault(key, 0 if is_opening else last)   # openings start at move 0

    def go(to: int):                 # runs before the rerun, so the slider picks it up
        ss[key] = max(0, min(last, to))

    # Title and explanation first, so the board and the step buttons end up on one screen.
    st.markdown(f"#### {game['title'] if is_opening else 'Review - ' + game['title']}")
    if is_opening:
        if info["intro"]:
            st.caption(info["intro"])
    else:
        st.caption(f"Result: {game['result']}" + (f" · AI level: {game['level']}" if game["level"] else ""))

    left, right = st.columns([3, 2])
    with right:
        with st.container(horizontal=True):
            st.button("⏮", key="rv_first", on_click=go, args=(0,))
            st.button("◀", key="rv_prev", on_click=go, args=(ss[key] - 1,))
            st.button("▶", key="rv_next", on_click=go, args=(ss[key] + 1,))
            st.button("⏭", key="rv_last", on_click=go, args=(last,))
        ply = ss[key]
        if ply and ply <= len(info["notes"]) and info["notes"][ply - 1]:
            st.info(f"💬 **{sans[ply - 1]}** - {info['notes'][ply - 1]}")
        if last:
            st.slider("Move", 0, last, key=key)
        st.code(san_table(sans) or "No moves", language=None)
        st.download_button("Download PGN", game["pgn"], file_name=f"chesso_{game_id}.pgn")
        with st.container(horizontal=True):
            if extra:
                extra()
            if on_close and st.button("← Back", key="rv_back"):
                on_close()
                st.rerun()
            if not is_opening and st.button("🗑 Delete game", key="rv_delete"):
                db.delete_game(engine, game_id)
                ss.pop(key, None)
                if on_close:
                    on_close()
                st.rerun()
    with left:
        names = {chess.WHITE: "White", chess.BLACK: "Black"}
        if game["mode"] == "vs_ai":
            you = chess.WHITE if game["human_color"] == "white" else chess.BLACK
            names = {you: "You", (not you): "AI"}
        board_with_captures(boards[ss[key]], key="rv_board_ui",
                            flipped=(game["human_color"] == "black"), interactive=False, names=names)


# ------------------------------------------------------------------------- Openings
@st.dialog("Famous openings")
def openings_dialog(rows):
    st.caption("Tap an opening to load it, then step through it move by move.")
    for i, r in enumerate(rows, start=1):
        sans, _, _ = db.pgn_to_positions(r["pgn"])
        if st.button(f"{i}. {r['title']} · {len(sans)} moves", key=f"op_{r['id']}",
                     use_container_width=True):
            st.session_state.op_gid = r["id"]
            st.session_state.pop(f"slider_{r['id']}", None)
            st.rerun()


def page_openings(engine):
    ss = st.session_state
    rows = sorted(db.list_games(engine, mode="opening", status=None), key=lambda r: r["id"])
    if not rows:
        st.info("No openings found in the database.")
        return
    if ss.get("op_gid") not in [r["id"] for r in rows]:
        ss.op_gid = rows[0]["id"]
    if ss.pop("op_show_load", False):
        openings_dialog(rows)

    def load_button():
        if st.button("📂 Load", key="op_load", help="Choose another opening"):
            ss.op_show_load = True
            st.rerun()

    replay_view(engine, ss.op_gid, extra=load_button)


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
    ss.ai_review, ss.ai_redo = None, []


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
    ss.ai_review, ss.ai_redo = None, []


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


def _ai_human_moves(board: chess.Board, human: bool) -> int:
    """How many of the moves played so far were the human's."""
    return sum(1 for i in range(len(board.move_stack)) if (i % 2 == 0) == (human == chess.WHITE))


def _ai_back():
    """Take back to your own previous move: undo the AI's reply and your move (2 plies)."""
    ss = st.session_state
    board, human = ss.ai_board, chess.WHITE if ss.ai_color == "white" else chess.BLACK
    while board.move_stack:
        ss.ai_redo.append(board.pop())
        if board.turn == human:        # back to a position where it's your move again
            break


def _ai_forward():
    """Replay your undone move and, if there is one, the AI's reply."""
    ss = st.session_state
    board, human = ss.ai_board, chess.WHITE if ss.ai_color == "white" else chess.BLACK
    if ss.ai_redo:
        board.push(ss.ai_redo.pop())
    if ss.ai_redo and board.turn != human:
        board.push(ss.ai_redo.pop())


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


def _ai_label(r, sans, finished: bool) -> str:
    bits = [r["level"], (r["human_color"] or "white").title()]
    if finished:
        bits.append(r["result"])
    bits += [f"{len(sans)} moves", f"{(r['updated_at'] or r['created_at']):%b %d}"]
    return " · ".join(bits)


@st.dialog("Your games vs the AI")
def load_dialog(engine):
    ss = st.session_state
    in_progress = db.list_in_progress(engine)
    finished = db.list_games(engine, mode="vs_ai", status="finished")
    if not in_progress and not finished:
        st.write("No saved games yet. Press 💾 Save during a game, or finish one.")
        return

    def section(title, rows, is_finished):
        st.markdown(f"**{title}**")
        if not rows:
            st.caption("None yet.")
        for r in rows:
            sans, _, _ = db.pgn_to_positions(r["pgn"])
            with st.container(horizontal=True, vertical_alignment="center"):
                if st.button(_ai_label(r, sans, is_finished), key=f"load_{r['id']}"):
                    if is_finished:               # just look at it; your current game stays put
                        ss.ai_review = r["id"]
                        ss.pop(f"slider_{r['id']}", None)
                        st.rerun()
                    _ai_request(engine, ("load", r["id"]))
                if st.button("🗑", key=f"del_{r['id']}", help="Delete this game"):
                    db.delete_game(engine, r["id"])
                    ss.show_load = True
                    st.rerun()

    section("In progress - tap to resume", in_progress, False)
    section("Finished - tap to review", finished, True)
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

    if ss.get("ai_review"):
        def close():
            ss.ai_review = None
        st.caption("Reviewing a finished game. Your current game is untouched.")
        replay_view(engine, ss.ai_review, on_close=close)
        return

    board: chess.Board = ss.ai_board
    human = chess.WHITE if ss.ai_color == "white" else chess.BLACK

    ai_turn = not game_over(board) and not ss.ai_resigned and board.turn != human

    ss.setdefault("ai_redo", [])
    st.markdown(f"#### You vs AI - {ss.ai_level}")
    left, right = st.columns([3, 2])
    with left:
        live = not game_over(board) and not ss.ai_resigned and board.turn == human
        names = {human: "You", (not human): f"AI"}
        mv = board_with_captures(board, key="ai_board_ui", flipped=(human == chess.BLACK),
                                 interactive=live, names=names)
        if mv:
            board.push(mv)
            ss.ai_redo = []            # a new move overwrites whatever was taken back
            st.rerun()
    with right:
        over = game_over(board) or ss.ai_resigned
        with st.container(horizontal=True):
            st.button("◀ Back", key="ai_back", on_click=_ai_back,
                      disabled=over or _ai_human_moves(board, human) == 0,
                      help="Take back your last move (and the AI's reply)")
            st.button("Forward ▶", key="ai_fwd", on_click=_ai_forward,
                      disabled=over or not ss.ai_redo, help="Replay the move you took back")
        st.info(f"AI ({ss.ai_level}) is thinking..." if ai_turn else status_text(board))
        with st.container(horizontal=True):
            if st.button("💾 Save", key="ai_save", disabled=over or not board.move_stack,
                         help="Save this game so you can resume it later"):
                _ai_save_in_progress(engine)
                st.toast("Game saved. Load it any time from 'Load'.", icon="💾")
            if st.button("📂 Load", key="ai_load", help="Resume or review your games vs the AI"):
                ss.show_load = True
                st.rerun()
            if st.button("Resign", key="ai_resign", disabled=over):
                ss.ai_resigned = True
                ss.ai_redo = []
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
    st.success(f"Game over ({result}). Saved automatically - find it under 📂 Load → Finished.")


# ----------------------------------------------------------------------- Training mode
def _tr_moves(board: chess.Board) -> list[str]:
    return [m.uci() for m in board.move_stack]


def _tr_dirty() -> bool:
    """Moves on the board that aren't stored in the database yet."""
    ss = st.session_state
    return bool(ss.tr_board.move_stack) and _tr_moves(ss.tr_board) != ss.tr_saved_moves


def _tr_reset(board=None, game_id=None, title=""):
    ss = st.session_state
    ss.tr_board = board or chess.Board()
    ss.tr_redo, ss.tr_game_id = [], game_id
    ss.tr_saved_moves = _tr_moves(ss.tr_board) if game_id else []
    ss.tr_title_default = title
    ss.tr_ver = ss.get("tr_ver", 0) + 1       # new key -> the title box shows the new default


def _tr_title() -> str:
    ss = st.session_state
    return (ss.get(f"tr_title_{ss.tr_ver}") or "").strip() or "Untitled line"


def _tr_save(engine) -> int:
    ss = st.session_state
    board = ss.tr_board
    pgn = db.board_to_pgn(board, white="Training", black="Training")
    result = board.result(claim_draw=True)
    if ss.tr_game_id:
        db.update_game(engine, ss.tr_game_id, pgn=pgn, result=result, status="finished", title=_tr_title())
    else:
        ss.tr_game_id = db.save_game(engine, mode="training", title=_tr_title(), pgn=pgn, result=result)
    ss.tr_saved_moves = _tr_moves(board)
    return ss.tr_game_id


def _tr_apply(engine, action):
    if action[0] == "load":
        row = db.get_game(engine, action[1])
        if not row:
            st.toast("That line no longer exists.")
            return
        _, boards, _ = db.pgn_to_positions(row["pgn"])
        _tr_reset(boards[-1], row["id"], row["title"])
    else:
        _tr_reset()


def _tr_request(engine, action):
    """Replace the board; ask first if it holds unsaved moves."""
    if _tr_dirty():
        st.session_state.tr_confirm = action
    else:
        _tr_apply(engine, action)
    st.rerun()


@st.dialog("Your training lines")
def tr_load_dialog(engine):
    rows = db.list_games(engine, mode="training", status=None)
    if not rows:
        st.write("No saved training lines yet. Make some moves and press 💾 Save.")
        return
    st.caption("Tap a line to load it onto the board.")
    for r in rows:
        sans, _, _ = db.pgn_to_positions(r["pgn"])
        label = f"{r['title']} · {len(sans)} moves · {(r['updated_at'] or r['created_at']):%b %d}"
        with st.container(horizontal=True, vertical_alignment="center"):
            if st.button(label, key=f"trload_{r['id']}"):
                _tr_request(engine, ("load", r["id"]))
            if st.button("🗑", key=f"trdel_{r['id']}", help="Delete this line"):
                db.delete_game(engine, r["id"])
                if st.session_state.tr_game_id == r["id"]:
                    st.session_state.tr_game_id = None
                st.session_state.tr_show_load = True
                st.rerun()
    if st.button("Cancel", key="trload_cancel"):
        st.rerun()


@st.dialog("Unsaved moves")
def tr_confirm_dialog(engine, action):
    st.write("The board has moves that aren't saved. Save this line before continuing?")
    if st.button("Save it, then continue", type="primary", use_container_width=True):
        _tr_save(engine)
        _tr_apply(engine, action)
        st.rerun()
    if st.button("Don't save, just continue", use_container_width=True):
        _tr_apply(engine, action)
        st.rerun()
    if st.button("Cancel", use_container_width=True):
        st.rerun()


def page_training(engine):
    ss = st.session_state
    if "tr_board" not in ss:
        _tr_reset()
    if ss.pop("tr_show_load", False):
        tr_load_dialog(engine)
    action = ss.pop("tr_confirm", None)
    if action:
        tr_confirm_dialog(engine, action)

    board: chess.Board = ss.tr_board
    st.markdown("#### Training - play both sides")
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
        with st.container(horizontal=True):
            if st.button("⏮", key="tr_first", disabled=not board.move_stack, help="Back to the start"):
                while board.move_stack:
                    ss.tr_redo.append(board.pop())
                st.rerun()
            if st.button("◀", key="tr_undo", disabled=not board.move_stack, help="Undo"):
                ss.tr_redo.append(board.pop())
                st.rerun()
            if st.button("▶", key="tr_redo_btn", disabled=not ss.tr_redo, help="Redo"):
                board.push(ss.tr_redo.pop())
                st.rerun()
            if st.button("⏭", key="tr_last", disabled=not ss.tr_redo, help="Forward to the end"):
                while ss.tr_redo:
                    board.push(ss.tr_redo.pop())
                st.rerun()
            if st.button("🔄 Flip", key="tr_flip_btn"):
                ss.tr_flip = not ss.get("tr_flip", False)
                st.rerun()
        st.markdown(f"**{status_text(board)}**")      # slim line (not a tall box) to save space
        st.text_input("Title", value=ss.tr_title_default, key=f"tr_title_{ss.tr_ver}",
                      placeholder="Title for this line, e.g. Italian Game ideas",
                      label_visibility="collapsed")
        with st.container(horizontal=True):
            if st.button("💾 Save", key="tr_save", type="primary", disabled=not board.move_stack):
                gid = _tr_save(engine)
                st.toast(f"Line saved (#{gid}).", icon="💾")
            if st.button("📂 Load", key="tr_load", help="Open one of your saved training lines"):
                ss.tr_show_load = True
                st.rerun()
            if st.button("🆕 New", key="tr_new", help="Start from the initial position"):
                _tr_request(engine, ("new",))
        st.code(san_table(_sans(board)) or "No moves yet", language=None)


# --------------------------------------------------------------------------------- main
def main():
    st.markdown(
        "<style>"
        ".stMainBlockContainer{padding-top:3.2rem !important}"
        "h4{padding:0.2rem 0 0 !important}"
        "div[data-testid=stVerticalBlock]{gap:0.6rem}"
        "@media (max-width:640px){.chesso-title{display:none}}"   # save vertical space on phones
        "</style><div class='chesso-title' style='font-size:1.75rem;font-weight:600;margin-bottom:.4rem'>"
        "♞ Chesso</div>", unsafe_allow_html=True)
    engine, is_neon = get_engine()
    if not is_neon:
        st.sidebar.warning("No DATABASE_URL set - using a local SQLite file. "
                           "Set your Neon URL to persist games in the cloud.")
    pages = {"Play vs AI": page_vs_ai, "Training mode": page_training, "Openings": page_openings}
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
