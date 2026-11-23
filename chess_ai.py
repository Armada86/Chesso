"""A small self-contained chess engine (negamax + alpha-beta) with 3 levels.

No external engine binary is required, so it runs anywhere Streamlit runs.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

import chess

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

# Piece-square tables, from White's point of view (index 0 = a1).
_PAWN = [
    0, 0, 0, 0, 0, 0, 0, 0,
    5, 10, 10, -20, -20, 10, 10, 5,
    5, -5, -10, 0, 0, -10, -5, 5,
    0, 0, 0, 20, 20, 0, 0, 0,
    5, 5, 10, 25, 25, 10, 5, 5,
    10, 10, 20, 30, 30, 20, 10, 10,
    50, 50, 50, 50, 50, 50, 50, 50,
    0, 0, 0, 0, 0, 0, 0, 0,
]
_KNIGHT = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20, 0, 5, 5, 0, -20, -40,
    -30, 5, 10, 15, 15, 10, 5, -30,
    -30, 0, 15, 20, 20, 15, 0, -30,
    -30, 5, 15, 20, 20, 15, 5, -30,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
]
_BISHOP = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10, 5, 0, 0, 0, 0, 5, -10,
    -10, 10, 10, 10, 10, 10, 10, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 5, 5, 10, 10, 5, 5, -10,
    -10, 0, 5, 10, 10, 5, 0, -10,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
]
_ROOK = [
    0, 0, 0, 5, 5, 0, 0, 0,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    5, 10, 10, 10, 10, 10, 10, 5,
    0, 0, 0, 0, 0, 0, 0, 0,
]
_QUEEN = [
    -20, -10, -10, -5, -5, -10, -10, -20,
    -10, 0, 5, 0, 0, 0, 0, -10,
    -10, 5, 5, 5, 5, 5, 0, -10,
    0, 0, 5, 5, 5, 5, 0, -5,
    -5, 0, 5, 5, 5, 5, 0, -5,
    -10, 0, 5, 5, 5, 5, 0, -10,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -20, -10, -10, -5, -5, -10, -10, -20,
]
_KING = [
    20, 30, 10, 0, 0, 10, 30, 20,
    20, 20, 0, 0, 0, 0, 20, 20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
]
PST = {
    chess.PAWN: _PAWN, chess.KNIGHT: _KNIGHT, chess.BISHOP: _BISHOP,
    chess.ROOK: _ROOK, chess.QUEEN: _QUEEN, chess.KING: _KING,
}

MATE = 100_000


@dataclass(frozen=True)
class Level:
    name: str
    depth: int          # search depth in plies
    blunder_rate: float  # chance of playing a random non-best move
    top_n: int          # pick among the N best moves when "blundering"
    time_limit: float   # seconds, safety cap


LEVELS: dict[str, Level] = {
    "Easy": Level("Easy", depth=1, blunder_rate=0.35, top_n=5, time_limit=2),
    "Medium": Level("Medium", depth=2, blunder_rate=0.10, top_n=3, time_limit=4),
    "Hard": Level("Hard", depth=3, blunder_rate=0.0, top_n=1, time_limit=6),
}


def evaluate(board: chess.Board) -> int:
    """Static evaluation in centipawns from the side to move's perspective."""
    if board.is_checkmate():
        return -MATE
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    score = 0
    for sq, piece in board.piece_map().items():
        idx = sq if piece.color == chess.WHITE else chess.square_mirror(sq)
        val = PIECE_VALUES[piece.piece_type] + PST[piece.piece_type][idx]
        score += val if piece.color == chess.WHITE else -val
    return score if board.turn == chess.WHITE else -score


def _order(board: chess.Board):
    def key(m: chess.Move) -> int:
        s = 0
        if board.is_capture(m):
            victim = board.piece_type_at(m.to_square) or chess.PAWN  # en passant
            attacker = board.piece_type_at(m.from_square)
            s += 10 * PIECE_VALUES[victim] - PIECE_VALUES[attacker] + 1000
        if m.promotion:
            s += PIECE_VALUES[m.promotion]
        if board.gives_check(m):
            s += 50
        return -s
    return sorted(board.legal_moves, key=key)


class _Timeout(Exception):
    pass


class _Search:
    def __init__(self, deadline: float):
        self.deadline = deadline
        self.nodes = 0

    def _tick(self):
        self.nodes += 1
        if self.nodes % 512 == 0 and time.monotonic() > self.deadline:
            raise _Timeout

    def quiesce(self, board, alpha, beta, qdepth=4):
        self._tick()
        stand = evaluate(board)
        if qdepth == 0 or stand >= beta:
            return stand
        alpha = max(alpha, stand)
        for m in _order(board):
            if not board.is_capture(m):
                continue
            board.push(m)
            score = -self.quiesce(board, -beta, -alpha, qdepth - 1)
            board.pop()
            if score >= beta:
                return score
            alpha = max(alpha, score)
        return alpha

    def negamax(self, board, depth, alpha, beta, ply=0):
        self._tick()
        if board.is_checkmate():
            return -MATE + ply
        if board.is_stalemate() or board.is_insufficient_material() \
                or board.can_claim_fifty_moves() or board.is_repetition(3):
            return 0
        if depth == 0:
            return self.quiesce(board, alpha, beta)
        best = -MATE * 2
        for m in _order(board):
            board.push(m)
            score = -self.negamax(board, depth - 1, -beta, -alpha, ply + 1)
            board.pop()
            if score > best:
                best = score
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        return best


def _score_root(board: chess.Board, depth: int, deadline: float):
    """Return [(score, move)] sorted best-first for the root position."""
    search = _Search(deadline)
    scored = []
    for m in _order(board):
        board.push(m)
        score = -search.negamax(board, depth - 1, -MATE * 2, MATE * 2, 1)
        board.pop()
        scored.append((score, m))
    scored.sort(key=lambda t: -t[0])
    return scored


def choose_move(board: chess.Board, level: str = "Medium",
                rng: random.Random | None = None) -> chess.Move:
    """Pick a move for the side to move at the given level."""
    rng = rng or random
    cfg = LEVELS[level]
    board = board.copy(stack=True)
    legal = list(board.legal_moves)
    if not legal:
        raise ValueError("No legal moves")
    start = time.monotonic()
    scored = None
    # Iterative deepening so the time cap still yields the last completed depth.
    for d in range(1, cfg.depth + 1):
        try:
            scored = _score_root(board, d, start + cfg.time_limit)
        except _Timeout:
            break
    if scored is None:
        return rng.choice(legal)
    if cfg.blunder_rate and rng.random() < cfg.blunder_rate:
        return rng.choice([m for _, m in scored[: cfg.top_n]])
    # Choose randomly among moves that are equally best (variety).
    top = [m for s, m in scored if s == scored[0][0]]
    return rng.choice(top)
