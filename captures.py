"""Captured-piece bookkeeping (pure logic, no Streamlit)."""
from __future__ import annotations

import chess

ORDER = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]
VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def captured_pieces(board: chess.Board) -> dict[bool, list[chess.Piece]]:
    """{color: pieces that color has captured}, rebuilt from the move list."""
    replay, out = board.root(), {chess.WHITE: [], chess.BLACK: []}
    for mv in board.move_stack:
        if replay.is_capture(mv):
            taken = (chess.Piece(chess.PAWN, not replay.turn) if replay.is_en_passant(mv)
                     else replay.piece_at(mv.to_square))
            out[replay.turn].append(taken)
        replay.push(mv)
    for lst in out.values():
        lst.sort(key=lambda p: ORDER.index(p.piece_type))
    return out


def material_lead(board: chess.Board) -> int:
    """White's material minus Black's, from the pieces still on the board."""
    return sum(VALUE[p.piece_type] * (1 if p.color else -1) for p in board.piece_map().values())
