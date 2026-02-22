"""Vendored utility functions from lichess-puzzler/tagger/util.py.

Upstream: https://github.com/ornicar/lichess-puzzler
Commit: d021969ec326c83cfa357f3ad58dbd9cea44e64f
License: AGPL-3.0

Modifications from upstream are marked with "# MODIFIED:" comments.
Functions not relevant to our use case (node-based helpers that require
chess.pgn.ChildNode) are omitted — we operate on chess.Board directly.
"""

# MODIFIED: removed imports for chess.pgn.ChildNode (not used in board-level API)
# MODIFIED: removed pp() debug helper, moved_piece_type(), is_advanced_pawn_move(),
#           is_very_advanced_pawn_move(), is_king_move(), is_castling(), is_capture(),
#           next_node(), next_next_node() — all require ChildNode, not applicable
from typing import List, Tuple

import chess
from chess import BISHOP, KING, KNIGHT, PAWN, QUEEN, ROOK, Board, Color, Piece, Square

values = {PAWN: 1, KNIGHT: 3, BISHOP: 3, ROOK: 5, QUEEN: 9}
king_values = {PAWN: 1, KNIGHT: 3, BISHOP: 3, ROOK: 5, QUEEN: 9, KING: 99}
ray_piece_types = [QUEEN, ROOK, BISHOP]


def piece_value(piece_type: chess.PieceType) -> int:
    return values[piece_type]


def material_count(board: Board, side: Color) -> int:
    return sum(
        len(board.pieces(piece_type, side)) * value
        for piece_type, value in values.items()
    )


def material_diff(board: Board, side: Color) -> int:
    return material_count(board, side) - material_count(board, not side)


def attacked_opponent_squares(
    board: Board, from_square: Square, pov: Color
) -> List[Tuple[Piece, Square]]:
    pieces = []
    for attacked_square in board.attacks(from_square):
        attacked_piece = board.piece_at(attacked_square)
        if attacked_piece and attacked_piece.color != pov:
            pieces.append((attacked_piece, attacked_square))
    return pieces


def is_defended(board: Board, piece: Piece, square: Square) -> bool:
    if board.attackers(piece.color, square):
        return True
    # ray defense https://lichess.org/editor/6k1/3q1pbp/2b1p1p1/1BPp4/rp1PnP2/4PRNP/4Q1P1/4B1K1_w_-_-_0_1
    for attacker in board.attackers(not piece.color, square):
        attacker_piece = board.piece_at(attacker)
        assert attacker_piece
        if attacker_piece.piece_type in ray_piece_types:
            bc = board.copy(stack=False)
            bc.remove_piece_at(attacker)
            if bc.attackers(piece.color, square):
                return True

    return False


def is_hanging(board: Board, piece: Piece, square: Square) -> bool:
    return not is_defended(board, piece, square)


def can_be_taken_by_lower_piece(board: Board, piece: Piece, square: Square) -> bool:
    for attacker_square in board.attackers(not piece.color, square):
        attacker = board.piece_at(attacker_square)
        assert attacker
        if (
            attacker.piece_type != chess.KING
            and values[attacker.piece_type] < values[piece.piece_type]
        ):
            return True
    return False


def is_in_bad_spot(board: Board, square: Square) -> bool:
    # hanging or takeable by lower piece
    piece = board.piece_at(square)
    assert piece
    return bool(board.attackers(not piece.color, square)) and (
        is_hanging(board, piece, square)
        or can_be_taken_by_lower_piece(board, piece, square)
    )


def is_trapped(board: Board, square: Square) -> bool:
    if board.is_check() or board.is_pinned(board.turn, square):
        return False
    piece = board.piece_at(square)
    assert piece
    if piece.piece_type in [PAWN, KING]:
        return False
    if not is_in_bad_spot(board, square):
        return False
    for escape in board.legal_moves:
        if escape.from_square == square:
            capturing = board.piece_at(escape.to_square)
            if capturing and values[capturing.piece_type] >= values[piece.piece_type]:
                return False
            board.push(escape)
            if not is_in_bad_spot(board, escape.to_square):
                board.pop()
                return False
            board.pop()
    return True


def attacker_pieces(board: Board, color: Color, square: Square) -> List[Piece]:
    return [
        p for p in [board.piece_at(s) for s in board.attackers(color, square)] if p
    ]
