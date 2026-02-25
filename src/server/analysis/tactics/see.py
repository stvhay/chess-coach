"""Static Exchange Evaluation (SEE): estimates material outcome of capture chains."""

import chess

# Centipawn piece values for SEE calculations
_PIECE_VALUES: dict[chess.PieceType, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 300,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 10000,  # effectively infinite — king can capture but can't be lost
}


def _can_capture_on(
    board: chess.Board, attacker_sq: chess.Square, target_sq: chess.Square, color: chess.Color
) -> bool:
    """Check if piece on attacker_sq can actually capture on target_sq.

    Returns False if the piece is pinned to its king and the target
    is not on the pin ray (moving there would be illegal).
    """
    if not board.is_pinned(color, attacker_sq):
        return True
    # Piece is pinned — check if target is on the pin ray
    pin_mask = board.pin(color, attacker_sq)
    return bool(pin_mask & chess.BB_SQUARES[target_sq])


def _get_sorted_attackers(
    board: chess.Board, target: chess.Square, color: chess.Color
) -> list[tuple[int, chess.Square]]:
    """Attackers of target by color, sorted by piece value ascending, filtered for pin-legality."""
    attackers = board.attackers(color, target)
    result = []
    for sq in attackers:
        if not _can_capture_on(board, sq, target, color):
            continue
        pt = board.piece_type_at(sq)
        if pt is None:
            continue
        result.append((_PIECE_VALUES[pt], sq))
    result.sort(key=lambda x: x[0])
    return result


def see(board: chess.Board, target: chess.Square, attacker_color: chess.Color) -> int:
    """Static Exchange Evaluation: material delta if attacker_color captures on target.

    Returns centipawns: positive if attacker wins material, negative if loses.
    Pin-aware: defenders pinned away from the target square are skipped.

    Algorithm:
    1. Build a gain list by alternating captures with least valuable pieces
    2. Each side can choose to "stand pat" (stop capturing) if continuing loses material
    3. Back-propagate this stand-pat logic from the end to get the true SEE value
    """
    target_piece_type = board.piece_type_at(target)
    if target_piece_type is None:
        return 0

    # Get initial attackers for both sides
    attackers = _get_sorted_attackers(board, target, attacker_color)
    if not attackers:
        return 0

    defender_color = not attacker_color

    # Build the gain list using a simulated capture chain
    # We simulate captures by removing pieces from the board's occupancy
    # but we use a simpler approach: just track which squares have been "used"

    gain = []
    gain.append(_PIECE_VALUES[target_piece_type])  # gain[0] = value of piece on target

    # The piece that just captured and sits on the target square (can be recaptured)
    current_piece_value = attackers[0][0]

    # Track squares whose pieces have been "used up" in the capture chain
    used_squares = {attackers[0][1]}

    # We need to work with a copy of the board to properly handle x-ray attackers
    # that become revealed when pieces are removed from the capture chain.
    # Use board.copy() and actually remove pieces for accurate x-ray detection.
    sim_board = board.copy()

    # Make the first capture: remove the attacker from its square, remove target piece
    first_attacker_sq = attackers[0][1]
    sim_board.remove_piece_at(first_attacker_sq)
    sim_board.remove_piece_at(target)
    # Place the attacker on the target square
    attacker_piece = board.piece_at(first_attacker_sq)
    sim_board.set_piece_at(target, attacker_piece)

    depth = 1
    current_color = defender_color  # defender captures next

    while True:
        # Find least valuable attacker for current_color that can capture on target
        next_attackers = _get_sorted_attackers(sim_board, target, current_color)

        if not next_attackers:
            break

        next_val, next_sq = next_attackers[0]

        # gain[d] = value_of_piece_just_captured - gain[d-1]
        # The piece on the target square is the one that captured last
        gain.append(current_piece_value - gain[depth - 1])

        current_piece_value = next_val

        # Simulate: remove capturer from its square, place it on target
        capturer_piece = sim_board.piece_at(next_sq)
        sim_board.remove_piece_at(next_sq)
        sim_board.remove_piece_at(target)
        sim_board.set_piece_at(target, capturer_piece)

        depth += 1
        current_color = not current_color

    # Back-propagation: each side can stand pat
    # From the end, each player chooses the better of capturing or not
    while depth > 1:
        depth -= 1
        gain[depth - 1] = -max(-gain[depth - 1], gain[depth])

    return gain[0]
