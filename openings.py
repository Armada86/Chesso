"""Ten famous chess openings, stored as games (mode='opening') so they can be reviewed step by step.

Each opening is a main line in SAN with a short idea and notes on key moves. The notes are keyed by
ply (half-move) number, which the tests check against the move actually played there.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import chess
import chess.pgn

import db


@dataclass(frozen=True)
class Opening:
    name: str
    eco: str
    moves: str
    idea: str
    notes: dict[int, str] = field(default_factory=dict)  # ply (1 = White's first move) -> note


OPENINGS: list[Opening] = [
    Opening(
        "Italian Game", "C50",
        "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O O-O",
        "A classical opening: develop quickly, aim the bishop at f7 and fight for the centre. "
        "This is the quiet 'Giuoco Pianissimo' line - solid, with a slow manoeuvring game ahead.",
        {1: "White claims the centre and opens lines for the queen and bishop.",
         5: "The bishop eyes f7, Black's weakest square early in the game.",
         7: "Prepares d4 to build a strong pawn centre.",
         9: "The quiet plan: support e4 and keep the position solid before going on the attack."}),
    Opening(
        "Ruy Lopez", "C84",
        "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3",
        "One of the oldest and most respected openings. White pressures the knight that defends e5 "
        "and plays for a long, strategic middlegame. This is the Closed Ruy Lopez.",
        {5: "Attacks the knight that defends e5.",
         6: "The Morphy Defence: asks the bishop what it intends to do.",
         9: "White castles and allows ...Nxe4: after 6.d4 White gets strong play for the pawn.",
         11: "Defends e4, so ideas like Bxc6 followed by Nxe5 become real threats.",
         17: "A useful waiting move that stops ...Bg4 from pinning the knight on f3."}),
    Opening(
        "Sicilian Defence (Najdorf)", "B90",
        "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3 e5 Nb3 Be6",
        "The most popular reply to 1.e4. Black fights for the centre from the side and plays for a "
        "win, not just equality. The Najdorf is a favourite of world champions.",
        {2: "Black fights for d4 without mirroring White, creating an unbalanced game.",
         5: "White opens the centre; the exchange gives White a central pawn for Black's wing pawn.",
         10: "The Najdorf move: stops Nb5 and prepares ...b5.",
         11: "The 'English Attack' set-up: Be3, Qd2, f3 and long castling.",
         12: "Kicks the knight away and grabs space, but leaves the d5 square weak."}),
    Opening(
        "French Defence", "C11",
        "e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7 e5 Nfd7 Bxe7 Qxe7 f4 O-O Nf3 c5",
        "Solid and resilient. Black accepts a cramped position in return for a sturdy pawn chain and "
        "counterplay against White's d4 pawn. This is the Classical Variation.",
        {2: "Prepares ...d5, but the light-squared bishop is locked behind the e6 pawn.",
         9: "White gains space and chases the knight away from f6.",
         11: "White trades off Black's good dark-squared bishop.",
         16: "The typical French counter-strike: hit White's d4 pawn."}),
    Opening(
        "Caro-Kann Defence", "B18",
        "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6 h4 h6 Nf3 Nd7 h5 Bh7 Bd3 Bxd3 Qxd3 e6",
        "A rock-solid defence. Like the French, Black plays ...d5, but the c6 pawn leaves the light "
        "bishop free to develop. This is the Classical Variation.",
        {2: "Prepares ...d5 with pawn support, keeping the c8 bishop free.",
         8: "The point of the Caro-Kann: the bishop develops outside the pawn chain.",
         11: "White gains space and threatens h5 to harass the bishop.",
         18: "Black is happy to trade off White's attacking bishop.",
         20: "Black has a healthy pawn structure and no weaknesses."}),
    Opening(
        "Queen's Gambit Declined", "D63",
        "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 Nbd7 Rc1 c6 Bd3 dxc4 Bxc4 Nd5",
        "White challenges Black's d5 pawn. It is called a gambit, but White can win the pawn back, so "
        "Black can decline with ...e6 and keep a solid centre. This is the Orthodox Defence.",
        {3: "The Queen's Gambit: White attacks the d5 pawn with a wing pawn.",
         4: "Declining the pawn: Black keeps d5 and builds a solid chain.",
         7: "Pins the knight that defends d5.",
         16: "Black captures now: White's bishop is already on d3, so retaking with Bxc4 costs White a tempo.",
         18: "Exchanging pieces frees Black's cramped position."}),
    Opening(
        "King's Indian Defence", "E97",
        "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2 e5 O-O Nc6 d5 Ne7",
        "A hypermodern opening: Black lets White build a big centre, then attacks it. Famous for "
        "sharp kingside attacks. This is the Classical Variation.",
        {4: "Black fianchettoes the bishop instead of fighting for the centre right away.",
         7: "White builds a big pawn centre; Black plans to undermine it.",
         12: "The central strike that challenges White's d4 pawn.",
         15: "White closes the centre and gains space; Black will attack on the kingside with ...f5."}),
    Opening(
        "English Opening", "A29",
        "c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5 cxd5 Nxd5 Bg2 Nb6 O-O Be7",
        "A flexible flank opening. White controls d5 from the side and often reaches a 'Reversed "
        "Sicilian' where White is a tempo up.",
        {1: "White controls d5 from the flank and keeps the options open.",
         2: "Black takes the centre - a Sicilian Defence with colours reversed.",
         7: "The fianchetto: the bishop will pressure the long diagonal.",
         8: "Black challenges the centre directly.",
         11: "The bishop pressures the knight on d5 and the c6 square."}),
    Opening(
        "London System", "D02",
        "d4 d5 Nf3 Nf6 Bf4 e6 e3 c5 c3 Nc6 Nbd2 Bd6 Bg3 O-O",
        "A simple system that White can play against almost anything. Learn one set-up and get a "
        "solid, comfortable position - popular at every level.",
        {5: "The London move: develop the bishop before e3 closes it in.",
         7: "Solid pawn structure with d4, e3 and c3.",
         9: "Completes the solid triangle of pawns on c3, d4 and e3.",
         13: "White offers the bishop trade; recapturing with hxg3 opens the h-file."}),
    Opening(
        "King's Gambit", "C39",
        "e4 e5 f4 exf4 Nf3 g5 h4 g4 Ne5 Nf6 Bc4 d5 exd5 Bd6",
        "The romantic opening of the 19th century. White sacrifices a pawn for rapid development and "
        "an open f-file. This is the Kieseritzky Gambit.",
        {3: "White offers a pawn to deflect Black's e-pawn and open the f-file.",
         4: "Black accepts the gambit.",
         6: "Black defends the extra f4 pawn with ...g5.",
         7: "White attacks the g5 pawn at once.",
         9: "The knight lands on a strong central square after g4 attacked it."}),
]


def build_pgn(op: Opening) -> str:
    """Return the opening as PGN: headers, the idea as the game comment, notes as move comments."""
    game = chess.pgn.Game()
    game.headers.update({"Event": "Opening", "White": "White", "Black": "Black",
                         "ECO": op.eco, "Opening": op.name, "Result": "*"})
    game.comment = op.idea
    board, node = chess.Board(), game
    for ply, san in enumerate(op.moves.split(), start=1):
        move = board.parse_san(san)
        node = node.add_variation(move)
        board.push(move)
        if ply in op.notes:
            node.comment = op.notes[ply]
    return str(game)


def seed(engine) -> int:
    """Insert any of the ten openings that aren't in the database yet. Safe to run repeatedly."""
    have = {g["title"] for g in db.list_games(engine, mode="opening", status=None)}
    added = 0
    for op in OPENINGS:
        title = f"{op.name} ({op.eco})"
        if title not in have:
            db.save_game(engine, mode="opening", title=title, pgn=build_pgn(op))
            added += 1
    return added
