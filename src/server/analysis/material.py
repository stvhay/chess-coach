"""Material counting and imbalance detection."""

from dataclasses import dataclass

import chess

from server.analysis.constants import _PIECE_FIELDS, get_piece_value

__all__ = [
    "MaterialCount",
    "MaterialInfo",
    "analyze_material",
]


@dataclass
class MaterialCount:
    pawns: int = 0
    knights: int = 0
    bishops: int = 0
    rooks: int = 0
    queens: int = 0


@dataclass
class MaterialInfo:
    white: MaterialCount
    black: MaterialCount
    white_total: int
    black_total: int
    imbalance: int  # white_total - black_total
    white_bishop_pair: bool
    black_bishop_pair: bool


def _count_material(board: chess.Board, color: chess.Color) -> MaterialCount:
    return MaterialCount(
        pawns=len(board.pieces(chess.PAWN, color)),
        knights=len(board.pieces(chess.KNIGHT, color)),
        bishops=len(board.pieces(chess.BISHOP, color)),
        rooks=len(board.pieces(chess.ROOK, color)),
        queens=len(board.pieces(chess.QUEEN, color)),
    )


def _material_total(mc: MaterialCount) -> int:
    return sum(getattr(mc, fname) * val for fname, _, val in _PIECE_FIELDS)


def analyze_material(board: chess.Board) -> MaterialInfo:
    wc = _count_material(board, chess.WHITE)
    bc = _count_material(board, chess.BLACK)
    wt = _material_total(wc)
    bt = _material_total(bc)
    return MaterialInfo(
        white=wc,
        black=bc,
        white_total=wt,
        black_total=bt,
        imbalance=wt - bt,
        white_bishop_pair=(
            bool(board.pieces(chess.BISHOP, chess.WHITE) & chess.BB_LIGHT_SQUARES)
            and bool(board.pieces(chess.BISHOP, chess.WHITE) & chess.BB_DARK_SQUARES)
        ),
        black_bishop_pair=(
            bool(board.pieces(chess.BISHOP, chess.BLACK) & chess.BB_LIGHT_SQUARES)
            and bool(board.pieces(chess.BISHOP, chess.BLACK) & chess.BB_DARK_SQUARES)
        ),
    )
