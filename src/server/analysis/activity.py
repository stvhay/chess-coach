"""Piece activity and mobility analysis."""

from dataclasses import dataclass

import chess

from server.analysis.constants import CENTER_SQUARES, GamePhase
from server.analysis.king_safety import _pawn_attacks_bb

__all__ = [
    "PieceActivity",
    "ActivityInfo",
    "_assess_mobility",
    "analyze_activity",
]


@dataclass
class PieceActivity:
    square: str
    piece: str  # e.g. "N", "b"
    mobility: int
    centralization: int  # min distance to center squares
    assessment: str = ""  # "restricted", "normal", "active"


@dataclass
class ActivityInfo:
    white: list[PieceActivity]
    black: list[PieceActivity]
    white_total_mobility: int
    black_total_mobility: int


_MOBILITY_THRESHOLDS: dict[int, dict[str, tuple[int, int]]] = {
    # piece_type: {phase: (restricted_below, active_above)}
    chess.KNIGHT: {"default": (3, 5), "endgame": (2, 4)},
    chess.BISHOP: {"default": (4, 8), "endgame": (3, 6)},
    chess.ROOK:   {"default": (5, 9), "endgame": (4, 7)},
    chess.QUEEN:  {"default": (8, 15), "endgame": (6, 12)},
}


def _assess_mobility(piece_type: int, mobility: int, phase: GamePhase | None = None) -> str:
    """Classify piece mobility as restricted, normal, or active."""
    thresholds = _MOBILITY_THRESHOLDS.get(piece_type, {"default": (3, 8)})
    key = "endgame" if phase == GamePhase.ENDGAME and "endgame" in thresholds else "default"
    low, high = thresholds[key]
    if mobility < low:
        return "restricted"
    elif mobility > high:
        return "active"
    return "normal"


def analyze_activity(board: chess.Board, phase: GamePhase | None = None) -> ActivityInfo:
    white_pieces: list[PieceActivity] = []
    black_pieces: list[PieceActivity] = []

    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        # Improved mobility area: exclude own pieces, enemy pawn attacks, own king square
        own_occupied = board.occupied_co[color]
        enemy_pawn_att = _pawn_attacks_bb(board, enemy)
        king_sq = board.king(color)
        king_bb = chess.BB_SQUARES[king_sq] if king_sq is not None else 0
        excluded = own_occupied | enemy_pawn_att | king_bb

        piece_list = white_pieces if color == chess.WHITE else black_pieces

        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            for sq in board.pieces(pt, color):
                mobility = len(chess.SquareSet(board.attacks_mask(sq) & ~excluded))
                cent = min(chess.square_distance(sq, c) for c in CENTER_SQUARES)
                symbol = chess.Piece(pt, color).symbol()
                piece_list.append(PieceActivity(
                    square=chess.square_name(sq),
                    piece=symbol,
                    mobility=mobility,
                    centralization=cent,
                    assessment=_assess_mobility(pt, mobility, phase),
                ))

    return ActivityInfo(
        white=white_pieces,
        black=black_pieces,
        white_total_mobility=sum(p.mobility for p in white_pieces),
        black_total_mobility=sum(p.mobility for p in black_pieces),
    )
