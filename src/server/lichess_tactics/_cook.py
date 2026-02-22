"""Vendored detection functions from lichess-puzzler/tagger/cook.py.

Upstream: https://github.com/ornicar/lichess-puzzler
Commit: d021969ec326c83cfa357f3ad58dbd9cea44e64f
License: AGPL-3.0

Only functions adapted for static position / PV-line analysis are included.
Original puzzle-mainline-oriented functions are omitted (tracked as 'skipped'
in upstream.json). Modifications marked with "# MODIFIED:" comments.
"""

# MODIFIED: adapted from puzzle-mainline iteration to static board analysis

import chess
from chess import BISHOP, KING, KNIGHT, PAWN, QUEEN, ROOK, Board, Piece, SquareSet
from chess import square_distance, square_file, square_rank

from server.lichess_tactics._util import (
    attacker_pieces,
    is_in_bad_spot,
    ray_piece_types,
)


# --- Double Check (trivial static detection) ---


def double_check(board: Board) -> bool:
    """Detect if the side to move is in double check."""
    return board.is_check() and len(board.checkers()) > 1


# --- Back-Rank Mate (static pattern on checkmate position) ---


def back_rank_mate(board: Board) -> bool:
    """Detect back-rank mate pattern in a checkmate position.

    The checkmated king is on its back rank, escape squares forward
    are blocked by own pieces, and the checking piece is on the same rank.
    """
    if not board.is_checkmate():
        return False

    # Determine loser (the side whose turn it is — they are mated)
    loser = board.turn
    winner = not loser
    king = board.king(loser)
    assert king is not None

    back_rank = 0 if loser == chess.WHITE else 7
    if square_rank(king) != back_rank:
        return False

    # Escape squares: one rank forward from king
    forward_rank = 1 if loser == chess.WHITE else 6
    escape_squares = SquareSet()
    king_file = square_file(king)
    for f in range(max(0, king_file - 1), min(8, king_file + 2)):
        escape_squares.add(chess.square(f, forward_rank))

    # All forward escape squares must be blocked by OWN pieces (not enemy, not empty)
    for sq in escape_squares:
        piece = board.piece_at(sq)
        if piece is None or piece.color == winner or board.attackers(winner, sq):
            return False

    # Checking piece must be on the back rank
    return any(square_rank(checker) == back_rank for checker in board.checkers())


# --- Smothered Mate (static pattern on checkmate position) ---


def smothered_mate(board: Board) -> bool:
    """Detect smothered mate: knight checkmate where all king escapes
    are blocked by the king's own pieces."""
    if not board.is_checkmate():
        return False

    loser = board.turn
    king = board.king(loser)
    assert king is not None

    for checker_square in board.checkers():
        piece = board.piece_at(checker_square)
        assert piece
        if piece.piece_type == KNIGHT:
            # Every adjacent square must be occupied by own pieces
            for sq in chess.SQUARES:
                if square_distance(sq, king) == 1:
                    blocker = board.piece_at(sq)
                    if not blocker or blocker.color != loser:
                        return False
            return True
    return False


# --- Arabian Mate ---


def arabian_mate(board: Board) -> bool:
    """Detect Arabian mate: rook mates king in corner, supported by knight."""
    if not board.is_checkmate():
        return False

    loser = board.turn
    winner = not loser
    king = board.king(loser)
    assert king is not None

    if square_file(king) not in [0, 7] or square_rank(king) not in [0, 7]:
        return False

    for checker in board.checkers():
        piece = board.piece_at(checker)
        assert piece
        if piece.piece_type == ROOK and square_distance(checker, king) == 1:
            for knight_sq in board.attackers(winner, checker):
                knight = board.piece_at(knight_sq)
                if (
                    knight
                    and knight.piece_type == KNIGHT
                    and abs(square_rank(knight_sq) - square_rank(king)) == 2
                    and abs(square_file(knight_sq) - square_file(king)) == 2
                ):
                    return True
    return False


# --- Hook Mate ---


def hook_mate(board: Board) -> bool:
    """Detect hook mate: rook mates adjacent to king, defended by knight,
    knight defended by pawn."""
    if not board.is_checkmate():
        return False

    loser = board.turn
    winner = not loser
    king = board.king(loser)
    assert king is not None

    for checker in board.checkers():
        piece = board.piece_at(checker)
        assert piece
        if piece.piece_type == ROOK and square_distance(checker, king) == 1:
            for knight_sq in board.attackers(winner, checker):
                knight = board.piece_at(knight_sq)
                if (
                    knight
                    and knight.piece_type == KNIGHT
                    and square_distance(knight_sq, king) == 1
                ):
                    for pawn_sq in board.attackers(winner, knight_sq):
                        pawn = board.piece_at(pawn_sq)
                        if pawn and pawn.piece_type == PAWN:
                            return True
    return False


# --- Anastasia Mate ---


def anastasia_mate(board: Board) -> bool:
    """Detect Anastasia mate: king on edge file (not corner), mated by Q/R
    on same file with own piece blocking adjacent file and knight supporting."""
    if not board.is_checkmate():
        return False

    loser = board.turn
    winner = not loser
    king = board.king(loser)
    assert king is not None

    if square_file(king) not in [0, 7] or square_rank(king) in [0, 7]:
        return False

    # Find checker on same file as king
    for checker in board.checkers():
        piece = board.piece_at(checker)
        assert piece
        if piece.piece_type in [QUEEN, ROOK] and square_file(checker) == square_file(king):
            # Normalize to a-file for analysis
            test_board = board.copy(stack=False)
            if square_file(king) != 0:
                test_board.apply_transform(chess.flip_horizontal)
            test_king = test_board.king(loser)
            assert test_king is not None
            # Own piece blocking on adjacent file (b-file)
            blocker = test_board.piece_at(test_king + 1)
            if blocker is not None and blocker.color == loser:
                # Knight supporting from 3 squares away
                knight = test_board.piece_at(test_king + 3)
                if (
                    knight is not None
                    and knight.color == winner
                    and knight.piece_type == KNIGHT
                ):
                    return True
    return False


# --- Dovetail Mate ---


def dovetail_mate(board: Board) -> bool:
    """Detect dovetail mate: queen mates a non-edge king diagonally, where
    every adjacent square is controlled solely by the queen or blocked by
    friendly pieces."""
    if not board.is_checkmate():
        return False

    loser = board.turn
    winner = not loser
    king = board.king(loser)
    assert king is not None

    if square_file(king) in [0, 7] or square_rank(king) in [0, 7]:
        return False

    # Find the checking queen
    queen_square = None
    for checker in board.checkers():
        piece = board.piece_at(checker)
        assert piece
        if piece.piece_type == QUEEN:
            queen_square = checker
            break
    if queen_square is None:
        return False

    # Queen must be diagonally adjacent
    if (
        square_file(queen_square) == square_file(king)
        or square_rank(queen_square) == square_rank(king)
        or square_distance(queen_square, king) > 1
    ):
        return False

    # Every adjacent square must be controlled solely by queen or blocked by own piece
    for sq in chess.SQUARES:
        if square_distance(sq, king) != 1:
            continue
        if sq == queen_square:
            continue
        attackers = list(board.attackers(winner, sq))
        if attackers == [queen_square]:
            if board.piece_at(sq):
                return False
        elif attackers:
            return False
    return True


# --- Boden's Mate / Double Bishop Mate ---


def boden_or_double_bishop_mate(board: Board) -> str | None:
    """Detect Boden's mate or double bishop mate.
    Returns 'bodenMate', 'doubleBishopMate', or None."""
    if not board.is_checkmate():
        return None

    loser = board.turn
    winner = not loser
    king = board.king(loser)
    assert king is not None

    bishop_squares = list(board.pieces(BISHOP, winner))
    if len(bishop_squares) < 2:
        return None

    for sq in chess.SQUARES:
        if square_distance(sq, king) >= 2:
            continue
        if not all(
            p.piece_type == BISHOP
            for p in attacker_pieces(board, winner, sq)
        ):
            return None

    if (square_file(bishop_squares[0]) < square_file(king)) == (
        square_file(bishop_squares[1]) > square_file(king)
    ):
        return "bodenMate"
    else:
        return "doubleBishopMate"


# --- Exposed King (static position check) ---
# MODIFIED: adapted from puzzle-mainline to static position analysis


def exposed_king(board: Board, pov: chess.Color) -> bool:
    """Check if the opponent's king is exposed (advanced, no pawn shield).

    pov: the attacking side's color.
    """
    opponent = not pov
    king = board.king(opponent)
    if king is None:
        return False

    # King must be advanced (rank > 4 from their perspective)
    if opponent == chess.WHITE:
        if square_rank(king) < 5:
            return False
    else:
        if square_rank(king) > 2:
            return False

    # No pawn shield
    adjacent = SquareSet()
    kf = square_file(king)
    kr = square_rank(king)
    shield_rank = kr - 1 if opponent == chess.WHITE else kr + 1
    if 0 <= shield_rank <= 7:
        for f in range(max(0, kf - 1), min(8, kf + 2)):
            adjacent.add(chess.square(f, shield_rank))

    for sq in adjacent:
        if board.piece_at(sq) == Piece(PAWN, opponent):
            return False

    return True
