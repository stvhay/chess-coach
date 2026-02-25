"""Development and space analysis."""

from dataclasses import dataclass

import chess

from server.analysis.constants import STARTING_MINORS
from server.analysis.king_safety import KingSafety, analyze_king_safety
from server.analysis.structure import _analyze_square_control

__all__ = [
    "Development",
    "Space",
    "analyze_development",
    "analyze_space",
    "_count_developed",
]


@dataclass
class Development:
    white_developed: int  # 0-4
    black_developed: int  # 0-4
    white_castled: str
    black_castled: str


def analyze_development(
    board: chess.Board,
    king_safety_white: KingSafety | None = None,
    king_safety_black: KingSafety | None = None,
) -> Development:
    # TODO(audit#6): castled coupling — reads KingSafety.castled because both
    # stubs share the same square-position heuristic. Will be decoupled when
    # KingSafety and Development get Stockfish-backed implementations.
    ks_w = king_safety_white or analyze_king_safety(board, chess.WHITE)
    ks_b = king_safety_black or analyze_king_safety(board, chess.BLACK)

    return Development(
        white_developed=_count_developed(board, chess.WHITE),
        black_developed=_count_developed(board, chess.BLACK),
        white_castled=ks_w.castled,
        black_castled=ks_b.castled,
    )


@dataclass
class Space:
    white_squares: int      # squares with net white control in black's half (files c-f)
    black_squares: int      # squares with net black control in white's half (files c-f)
    white_occupied: int     # white pieces/pawns in black's half on files c-f
    black_occupied: int     # black pieces/pawns in white's half on files c-f


_SPACE_FILES = range(2, 6)  # c, d, e, f (indices 2-5)


def analyze_space(board: chess.Board) -> Space:
    white_net = 0
    black_net = 0
    white_occ = 0
    black_occ = 0

    for f in _SPACE_FILES:
        # White space: squares in black's half (ranks 4-7, i.e. ranks 5-8)
        for r in range(4, 8):
            sq = chess.square(f, r)
            sc = _analyze_square_control(board, sq)
            white_attacks = sc.white_pawn_attacks + sc.white_piece_attacks
            black_attacks = sc.black_pawn_attacks + sc.black_piece_attacks
            if white_attacks > black_attacks:
                white_net += 1
            # Occupation: white piece/pawn on this square
            if sc.occupied_by is not None and sc.occupied_by.startswith("white"):
                white_occ += 1

        # Black space: squares in white's half (ranks 0-3, i.e. ranks 1-4)
        for r in range(0, 4):
            sq = chess.square(f, r)
            sc = _analyze_square_control(board, sq)
            white_attacks = sc.white_pawn_attacks + sc.white_piece_attacks
            black_attacks = sc.black_pawn_attacks + sc.black_piece_attacks
            if black_attacks > white_attacks:
                black_net += 1
            # Occupation: black piece/pawn on this square
            if sc.occupied_by is not None and sc.occupied_by.startswith("black"):
                black_occ += 1

    return Space(
        white_squares=white_net,
        black_squares=black_net,
        white_occupied=white_occ,
        black_occupied=black_occ,
    )


def _count_developed(board: chess.Board, color: chess.Color) -> int:
    """Count surviving minor pieces not on their starting squares."""
    total_minors = (
        len(board.pieces(chess.KNIGHT, color))
        + len(board.pieces(chess.BISHOP, color))
    )
    on_home = sum(
        1 for home_sq, pt in STARTING_MINORS[color]
        if (p := board.piece_at(home_sq)) is not None
        and p.color == color
        and p.piece_type == pt
    )
    return total_minors - on_home
