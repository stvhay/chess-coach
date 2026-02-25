"""Tactic valuation: compute TacticValue for each detected motif using SEE."""

import chess

from server.analysis.constants import get_piece_value
from server.analysis.tactics.see import _PIECE_VALUES, see
from server.analysis.tactics.types import (
    CapturableDefender,
    DiscoveredAttack,
    Fork,
    HangingPiece,
    OverloadedPiece,
    Pin,
    Skewer,
    TacticValue,
)


def _parse_color(color_name: str) -> chess.Color:
    """Convert "white"/"black" string to chess.Color."""
    return chess.WHITE if color_name == "white" else chess.BLACK


def _build_defense_notes(
    board: chess.Board,
    target_sq: chess.Square,
    defended_color: chess.Color,
) -> str:
    """Explain why defenders of target_sq cannot actually defend it.

    Checks each defender for absolute pins (to king). If a defender is
    pinned and the target is NOT on the pin ray, it cannot recapture —
    note that fact. Consistent with SEE's _can_capture_on() logic.
    """
    notes: list[str] = []
    for def_sq in board.attackers(defended_color, target_sq):
        if not board.is_pinned(defended_color, def_sq):
            continue
        pin_mask = board.pin(defended_color, def_sq)
        if pin_mask & chess.BB_SQUARES[target_sq]:
            continue  # target is on pin ray — defender CAN capture there
        # Defender is pinned off-ray and cannot defend target_sq
        def_piece = board.piece_at(def_sq)
        if def_piece is None:
            continue
        piece_char = chess.piece_symbol(def_piece.piece_type).upper()
        king_sq = board.king(defended_color)
        pinned_to = chess.square_name(king_sq) if king_sq is not None else "?"
        notes.append(
            f"defender {piece_char} on {chess.square_name(def_sq)} pinned to {pinned_to}"
        )
    return "; ".join(notes)


def _value_hanging(hanging: HangingPiece, board: chess.Board) -> TacticValue:
    """Value a hanging piece via SEE from the opponent's perspective."""
    sq = chess.parse_square(hanging.square)
    # Attacker is the opponent of the piece's owner
    attacker_color = not _parse_color(hanging.color)
    delta = see(board, sq, attacker_color)
    defense_notes = _build_defense_notes(board, sq, _parse_color(hanging.color))
    return TacticValue(material_delta=delta, is_sound=delta > 0, defense_notes=defense_notes)


def _value_pin(pin: Pin, board: chess.Board) -> TacticValue:
    """Value a pin.

    Absolute pin: the pinned piece is immobilized. Value = pinned piece value
    (the pinner threatens to win it, or at minimum immobilizes it).
    Relative pin: value = SEE of pinner capturing the pinned piece.
    """
    pinned_sq = chess.parse_square(pin.pinned_square)
    pinner_color = _parse_color(pin.color)

    if pin.is_absolute:
        # Absolute pin: value is the pinned piece
        pinned_type = board.piece_type_at(pinned_sq)
        if pinned_type is None:
            return TacticValue(material_delta=0, is_sound=False)
        delta = _PIECE_VALUES[pinned_type]
        return TacticValue(material_delta=delta, is_sound=True)
    else:
        # Relative pin: SEE of capturing the pinned piece
        delta = see(board, pinned_sq, pinner_color)
        return TacticValue(material_delta=delta, is_sound=delta > 0)


def _value_fork(fork: Fork, board: chess.Board) -> TacticValue:
    """Value a fork.

    The opponent must concede one target. They save their most valuable,
    we capture the next most valuable. For check forks, they must address
    the check first.
    """
    forker_sq = chess.parse_square(fork.forking_square)
    forker_color = _parse_color(fork.color)
    opponent_color = not forker_color

    # Sort targets by piece value descending
    target_values = []
    for t_name in fork.targets:
        t_sq = chess.parse_square(t_name)
        pt = board.piece_type_at(t_sq)
        if pt is None:
            continue
        val = _PIECE_VALUES.get(pt, 0)
        target_values.append((val, t_sq, pt))
    target_values.sort(key=lambda x: x[0], reverse=True)

    if len(target_values) < 2:
        return TacticValue(material_delta=0, is_sound=False)

    # For check fork: opponent must address check, we capture highest non-king target
    if fork.is_check_fork:
        # Find highest-value non-king target
        for val, sq, pt in target_values:
            if pt != chess.KING:
                delta = see(board, sq, forker_color)
                return TacticValue(material_delta=delta, is_sound=delta > 0)
        return TacticValue(material_delta=0, is_sound=False)

    # Non-check fork: opponent saves most valuable, we capture second
    second_val, second_sq, _ = target_values[1]
    delta = see(board, second_sq, forker_color)

    # Can opponent capture the forker profitably?
    forker_loss = see(board, forker_sq, opponent_color)
    if forker_loss > 0:
        # Opponent can win the forker — fork is less valuable
        delta = max(0, delta - forker_loss)

    return TacticValue(material_delta=delta, is_sound=delta > 0)


def _value_skewer(skewer: Skewer, board: chess.Board) -> TacticValue:
    """Value a skewer.

    Front piece is attacked and must move, exposing the behind piece.
    For absolute skewer (king in front): king MUST move.
    """
    behind_sq = chess.parse_square(skewer.behind_square)
    attacker_color = _parse_color(skewer.color)

    if skewer.is_absolute:
        # King must move — behind piece is capturable
        behind_type = board.piece_type_at(behind_sq)
        if behind_type is None:
            return TacticValue(material_delta=0, is_sound=False)
        # Approximate: value of behind piece (king must move, so no defense calculation
        # on the behind piece from the front piece)
        delta = _PIECE_VALUES[behind_type]
        return TacticValue(material_delta=delta, is_sound=True)
    else:
        # Non-absolute: front piece should move, behind piece exposed
        # Approximate with SEE on behind square
        delta = see(board, behind_sq, attacker_color)
        return TacticValue(material_delta=delta, is_sound=delta > 0)


def _value_discovered(da: DiscoveredAttack, board: chess.Board) -> TacticValue:
    """Value a discovered attack.

    After blocker moves, slider attacks target. Approximate by SEE on target.
    """
    target_sq = chess.parse_square(da.target_square)
    slider_color = _parse_color(da.color)
    delta = see(board, target_sq, slider_color)
    return TacticValue(material_delta=delta, is_sound=delta > 0)


def _value_capturable_defender(cd: CapturableDefender, board: chess.Board) -> TacticValue:
    """Value a capturable defender.

    Two-step: capture the defender, then the charge is undefended.
    """
    defender_sq = chess.parse_square(cd.defender_square)
    charge_sq = chess.parse_square(cd.charge_square)
    # Attacker color is the opposite of the defender's color
    attacker_color = not _parse_color(cd.color)

    # Step 1: cost of capturing the defender
    step1 = see(board, defender_sq, attacker_color)

    if step1 >= 0:
        # Capturing the defender is at least break-even
        # Step 2: charge is now undefended — value is the charge piece
        charge_type = board.piece_type_at(charge_sq)
        if charge_type is not None:
            step2 = _PIECE_VALUES[charge_type]
        else:
            step2 = 0
        delta = step1 + step2
    else:
        delta = step1

    return TacticValue(material_delta=delta, is_sound=delta > 0)


def _value_overloaded(op: OverloadedPiece, board: chess.Board) -> TacticValue:
    """Value an overloaded piece.

    Heuristic: the piece can't defend all duties. Value = minimum of the
    defended piece values (the weakest duty the opponent can exploit).
    """
    min_duty_value = float("inf")
    for sq_name in op.defended_squares:
        sq = chess.parse_square(sq_name)
        pt = board.piece_type_at(sq)
        if pt is not None:
            val = _PIECE_VALUES.get(pt, 0)
            if val < min_duty_value:
                min_duty_value = val

    if min_duty_value == float("inf"):
        return TacticValue(material_delta=0, is_sound=False, source="heuristic")

    delta = int(min_duty_value)
    return TacticValue(material_delta=delta, is_sound=delta > 0, source="heuristic")
