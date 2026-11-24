"""Legality checks for a hand-made chess position (pure logic, no Streamlit).

`validate_position` returns a list of plain-English problems; an empty list means the game can start.

What is checked: kings, pawn counts and placement, kings touching, whether the extra pieces
(e.g. a second queen, or two bishops on the same colour of square) could only have come from
promotions that the missing pawns allow, illegal checks, and positions that are already over.
It is not a full retrograde analysis (it does not prove every pawn structure is reachable).
"""
from __future__ import annotations

import chess

NAMES = {chess.WHITE: "White", chess.BLACK: "Black"}
LIGHT = chess.BB_LIGHT_SQUARES


def _count(board: chess.Board, color: bool, piece_type: int) -> int:
    return len(board.pieces(piece_type, color))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _promotion_problem(board: chess.Board, color: bool) -> str | None:
    """Extra pieces can only come from promoted pawns, and each promotion uses up one pawn."""
    pawns = _count(board, color, chess.PAWN)
    missing = 8 - pawns
    if missing < 0:               # too many pawns is reported separately
        return None
    queens = _count(board, color, chess.QUEEN)
    rooks = _count(board, color, chess.ROOK)
    knights = _count(board, color, chess.KNIGHT)
    bishops = board.pieces(chess.BISHOP, color)
    light = len([s for s in bishops if (1 << s) & LIGHT])
    dark = len(bishops) - light

    # (description of what's there, how many of them can't be original pieces)
    extras = [
        (f"{queens} queens", queens - 1),
        (f"{rooks} rooks", rooks - 2),
        (f"{knights} knights", knights - 2),
        (f"{light} bishops on light squares", light - 1),
        (f"{dark} bishops on dark squares", dark - 1),
    ]
    over = [(text, n) for text, n in extras if n > 0]
    needed = sum(n for _, n in over)
    if needed <= missing:
        return None
    who = NAMES[color]
    have = " and ".join(text for text, _ in over)
    why = ("Each side starts with 1 queen, 2 rooks, 2 knights and one bishop on each square colour, "
           "so anything extra must be a promoted pawn - ")
    if missing == 0:
        return f"{who} has {have}. {why}but {who} still has all 8 pawns."
    return (f"{who} has {have}. {why}but only {missing} {who} "
            f"{'pawn is' if missing == 1 else 'pawns are'} missing and {needed} would be needed.")


def validate_position(board: chess.Board) -> list[str]:
    """Return the reasons this position can't be played (empty list = it's fine)."""
    problems: list[str] = []

    kings_ok = True
    for color in (chess.WHITE, chess.BLACK):
        n = _count(board, color, chess.KING)
        if n != 1:
            kings_ok = False
            problems.append(f"{NAMES[color]} must have exactly one king (found {n}).")

    for color in (chess.WHITE, chess.BLACK):
        pawns = board.pieces(chess.PAWN, color)
        if len(pawns) > 8:
            problems.append(f"{NAMES[color]} has {len(pawns)} pawns - the maximum is 8.")
        bad = [chess.square_name(s) for s in pawns if chess.square_rank(s) in (0, 7)]
        if bad:
            problems.append(f"{NAMES[color]} has a pawn on the first or last rank ({', '.join(bad)}). "
                            "Pawns can never stand there.")
        if chess.popcount(board.occupied_co[color]) > 16:
            problems.append(f"{NAMES[color]} has more than 16 pieces.")
        elif (msg := _promotion_problem(board, color)):
            problems.append(msg)

    if kings_ok:
        wk, bk = board.king(chess.WHITE), board.king(chess.BLACK)
        if chess.square_distance(wk, bk) <= 1:
            problems.append("The two kings are touching. Kings must be at least one square apart.")
        else:
            mover = board.turn
            other = not mover
            if board.is_attacked_by(mover, board.king(other)):
                problems.append(
                    f"{NAMES[other]}'s king is in check, but it is {NAMES[mover]}'s turn. "
                    f"That can't happen - {NAMES[other]} would have just left their own king in check. "
                    "Change who moves first, or move a piece.")
            status = board.status()
            if status & chess.STATUS_TOO_MANY_CHECKERS:
                problems.append(f"{NAMES[mover]}'s king is attacked by more than two pieces at once, "
                                "which is impossible.")
            if status & chess.STATUS_IMPOSSIBLE_CHECK:
                problems.append(f"{NAMES[mover]}'s king is in a check that could not have been given "
                                "by a legal last move.")
            if not problems:
                if board.is_checkmate():
                    problems.append(f"{NAMES[mover]} is already checkmated, so the game would end at once.")
                elif board.is_stalemate():
                    problems.append(f"{NAMES[mover]} has no legal move (stalemate), so the game would "
                                    "end at once. Give them a move, or let the other side start.")
                elif board.is_insufficient_material():
                    problems.append("Neither side has enough pieces to ever give checkmate, "
                                    "so the game would be a draw at once.")
    return problems
