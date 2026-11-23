"""Clickable chess board: click a piece, click its destination.

A tiny bidirectional Streamlit component (plain HTML/JS, no build step).
"""
from __future__ import annotations

from pathlib import Path

import chess
import chess.svg
import streamlit as st
import streamlit.components.v1 as components

_component = components.declare_component(
    "chess_board", path=str(Path(__file__).parent / "chess_board_frontend"))


@st.cache_resource
def _piece_svgs() -> dict[str, str]:
    return {
        sym: chess.svg.piece(chess.Piece.from_symbol(sym), size=45)
        for sym in "PNBRQKpnbrqk"
    }


def _legal_map(board: chess.Board) -> dict:
    out: dict[str, dict[str, bool]] = {}
    for m in board.legal_moves:
        out.setdefault(chess.square_name(m.from_square), {})[chess.square_name(m.to_square)] = bool(m.promotion)
    return out


def chess_board(board: chess.Board, *, key: str, flipped: bool = False,
                interactive: bool = True) -> chess.Move | None:
    """Render the board; return a legal move if the user just made one, else None."""
    last = board.peek() if board.move_stack else None
    value = _component(
        fen=board.fen(),
        position={chess.square_name(s): p.symbol() for s, p in board.piece_map().items()},
        legal=_legal_map(board) if interactive else {},
        flipped=flipped,
        interactive=interactive,
        turn_white=board.turn == chess.WHITE,
        last=[chess.square_name(last.from_square), chess.square_name(last.to_square)] if last else None,
        check=chess.square_name(board.king(board.turn)) if board.is_check() else None,
        pieces=_piece_svgs(),
        key=key, default=None,
    )
    # The component keeps returning its last click on every rerun; act on each click once.
    if not value or not interactive:
        return None
    seen = f"_seen_{key}"
    if st.session_state.get(seen) == value["id"]:
        return None
    st.session_state[seen] = value["id"]
    promo = {"q": chess.QUEEN, "r": chess.ROOK, "b": chess.BISHOP, "n": chess.KNIGHT}.get(value.get("promo"))
    move = chess.Move(chess.parse_square(value["from"]), chess.parse_square(value["to"]), promotion=promo)
    return move if move in board.legal_moves else None  # server-side legality check
