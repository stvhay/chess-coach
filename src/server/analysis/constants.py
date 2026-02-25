"""Constants and small utility functions shared across analysis submodules."""

import enum
from dataclasses import dataclass, field

import chess

__all__ = [
    "CENTER_SQUARES",
    "get_piece_value",
    "_PIECE_FIELDS",
    "_colored",
    "_color_name",
    "STARTING_MINORS",
    "LONG_DIAGONALS",
    "GamePhase",
]

CENTER_SQUARES = [chess.D4, chess.E4, chess.D5, chess.E5]

def get_piece_value(piece_type: chess.PieceType, *, king=None) -> int:
    """Get standard piece value. King value must be explicitly provided.

    king=None (default) causes TypeError if caller forgets to handle king,
    which is the desired behavior — forces explicit handling.
    """
    return {
        chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
        chess.ROOK: 5, chess.QUEEN: 9, chess.KING: king,
    }[piece_type]


# Shared field mapping for MaterialCount ↔ piece values
_PIECE_FIELDS: list[tuple[str, chess.PieceType, int]] = [
    ("pawns", chess.PAWN, 1),
    ("knights", chess.KNIGHT, 3),
    ("bishops", chess.BISHOP, 3),
    ("rooks", chess.ROOK, 5),
    ("queens", chess.QUEEN, 9),
]

def _colored(piece_char: str) -> str:
    """Add color prefix: 'N' → 'White N', 'p' → 'Black P'."""
    color = "White" if piece_char.isupper() else "Black"
    return f"{color} {piece_char.upper()}"


def _color_name(color: chess.Color) -> str:
    """Convert chess.Color bool to lowercase string."""
    return "white" if color == chess.WHITE else "black"


STARTING_MINORS = {
    chess.WHITE: [
        (chess.B1, chess.KNIGHT),
        (chess.G1, chess.KNIGHT),
        (chess.C1, chess.BISHOP),
        (chess.F1, chess.BISHOP),
    ],
    chess.BLACK: [
        (chess.B8, chess.KNIGHT),
        (chess.G8, chess.KNIGHT),
        (chess.C8, chess.BISHOP),
        (chess.F8, chess.BISHOP),
    ],
}

LONG_DIAGONALS = [
    chess.BB_A1 | chess.BB_B2 | chess.BB_C3 | chess.BB_D4 | chess.BB_E5 | chess.BB_F6 | chess.BB_G7 | chess.BB_H8,
    chess.BB_A8 | chess.BB_B7 | chess.BB_C6 | chess.BB_D5 | chess.BB_E4 | chess.BB_F3 | chess.BB_G2 | chess.BB_H1,
]


class GamePhase(enum.Enum):
    OPENING = "opening"
    MIDDLEGAME = "middlegame"
    ENDGAME = "endgame"
