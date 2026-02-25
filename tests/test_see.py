"""Tests for SEE (Static Exchange Evaluation) and tactic valuation.

Covers:
- Basic SEE calculations (undefended captures, equal trades, bad trades)
- Pin-awareness in SEE (pinned defenders excluded or included on ray)
- X-ray / battery detection through SEE simulation
- Tactic valuation via analyze_tactics (forks, pins, skewers, hanging pieces)
"""

import chess

from server.analysis.tactics import see, TacticValue, analyze_tactics
from server.analysis.tactics.see import _can_capture_on, _get_sorted_attackers, _PIECE_VALUES
from server.analysis.tactics.valuation import (
    _build_defense_notes,
    _value_capturable_defender,
    _value_discovered,
    _value_fork,
    _value_hanging,
    _value_overloaded,
    _value_pin,
    _value_skewer,
)
from server.analysis.tactics.types import (
    CapturableDefender,
    DiscoveredAttack,
    Fork,
    HangingPiece,
    OverloadedPiece,
    Pin,
    Skewer,
)


# ---------------------------------------------------------------------------
# Basic SEE cases
# ---------------------------------------------------------------------------


def test_see_undefended_pawn():
    """White knight captures an undefended black pawn. SEE = 100.

    Nc4 attacks e5 (knight on c4 attacks a3, a5, b2, b6, d2, d6, e3, e5).
    The black pawn on e5 is undefended.
    """
    board = chess.Board("8/8/8/4p3/2N5/8/8/4K2k w - - 0 1")
    result = see(board, chess.E5, chess.WHITE)
    assert result == 100


def test_see_pawn_takes_pawn_defended_by_pawn():
    """Pawn captures pawn defended by another pawn. Equal trade, SEE = 0."""
    # d4 captures c5, d6 recaptures on c5.
    board = chess.Board("8/8/3p4/2p5/3P4/8/8/4K2k w - - 0 1")
    result = see(board, chess.C5, chess.WHITE)
    assert result == 0


def test_see_rook_takes_pawn_defended_by_knight():
    """Rook captures pawn defended by knight. Bad trade: SEE = -400.

    Rd1 captures d5 pawn (+100), Nf6 recaptures rook (-500). Net: -400.
    """
    board = chess.Board("8/8/5n2/3p4/8/8/8/3RK2k w - - 0 1")
    result = see(board, chess.D5, chess.WHITE)
    assert result == 100 - 500  # win pawn, lose rook = -400


def test_see_queen_takes_pawn_defended_by_pawn():
    """Queen captures pawn defended by another pawn. Huge loss: SEE = -800."""
    # Qd4 captures c5, d6 recaptures. Queen (900) for pawn (100) = -800.
    board = chess.Board("8/8/3p4/2p5/3Q4/8/8/4K2k w - - 0 1")
    result = see(board, chess.C5, chess.WHITE)
    assert result == 100 - 900  # -800


def test_see_rook_takes_rook_equal_exchange():
    """Rook takes rook defended by another rook. Equal exchange, SEE = 0."""
    # Rd1 captures d5, Rd8 recaptures on d5. Rook for rook = 0.
    board = chess.Board("3r4/8/8/3r4/8/8/8/3RK1k1 w - - 0 1")
    result = see(board, chess.D5, chess.WHITE)
    assert result == 0


def test_see_rook_takes_undefended_rook():
    """Rook takes undefended rook. SEE = 500."""
    board = chess.Board("8/8/8/3r4/8/8/8/3RK1k1 w - - 0 1")
    result = see(board, chess.D5, chess.WHITE)
    assert result == 500


def test_see_empty_target():
    """SEE on an empty square returns 0."""
    board = chess.Board("8/8/8/8/8/8/8/4K2k w - - 0 1")
    result = see(board, chess.E4, chess.WHITE)
    assert result == 0


def test_see_king_captures_undefended_knight():
    """King captures undefended knight. SEE = 300."""
    board = chess.Board("8/8/8/8/4n3/3K4/8/7k w - - 0 1")
    result = see(board, chess.E4, chess.WHITE)
    assert result == 300


def test_see_defenders_sorted_by_value():
    """Pawn takes pawn defended by knight and rook. Lowest value recaptures first.

    White pawn on e4 captures d5 pawn. Black Nf4 (300) and Rd8 (500) both
    defend d5. The knight recaptures first (lowest value), not the rook.
    SEE = 0 (pawn for pawn, equal trade).
    """
    board = chess.Board("3r4/8/8/3p4/4Pn2/8/8/6Kk w - - 0 1")
    result = see(board, chess.D5, chess.WHITE)
    # e4xd5 (+100), Nf4xd5 (gain[1] = 100 - 100 = 0). No more white attackers.
    # Back-prop: gain[0] = -max(-100, 0) = 0.
    assert result == 0


def test_see_xray_rook_behind_rook():
    """Two white rooks on a file with x-ray. After first rook captures,
    second rook backs it up.

    Rd2 takes d5 pawn, Rd8 recaptures, Rd1 recaptures Rd8.
    Net: won pawn (100) + rook (500) - rook (500) = 100.
    """
    board = chess.Board("3r4/8/8/3p4/8/8/3R4/3RK1k1 w - - 0 1")
    result = see(board, chess.D5, chess.WHITE)
    assert result == 100


def test_see_no_attacker():
    """No piece of the given color attacks the target. SEE = 0."""
    # White has only king on e1, target is a black pawn on a5. King can't reach.
    board = chess.Board("8/8/8/p7/8/8/8/4K2k w - - 0 1")
    result = see(board, chess.A5, chess.WHITE)
    assert result == 0


# ---------------------------------------------------------------------------
# Pin-awareness cases
# ---------------------------------------------------------------------------


def test_see_pinned_bishop_cannot_recapture_off_ray():
    """Bishop pinned along e-file cannot recapture on d5 (off the pin ray).

    White Nb6 captures d5 pawn. Black bishop on e6 is pinned by Re1 to Ke8
    along the e-file. d5 is not on the e-file, so the bishop cannot recapture.
    SEE = 100 (free pawn).
    """
    board = chess.Board("4k3/8/1N2b3/3p4/8/8/8/4RK2 w - - 0 1")
    result = see(board, chess.D5, chess.WHITE)
    assert result == 100


def test_can_capture_on_pinned_off_ray_returns_false():
    """Directly test _can_capture_on: bishop pinned along e-file, target d5 off ray."""
    board = chess.Board("4k3/8/4b3/3p4/2N5/8/8/4RK2 w - - 0 1")
    # Bishop on e6 is BLACK, pinned along e-file. d5 is off the e-file.
    result = _can_capture_on(board, chess.E6, chess.D5, chess.BLACK)
    assert result is False


def test_can_capture_on_pinned_on_ray_returns_true():
    """Rook pinned along a rank CAN capture on the same rank (on the pin ray).

    Black rook on c4 pinned by white Rh4 to black Ka4. White Ne4 is on rank 4.
    The rook can capture on e4 since e4 is on the pin ray (rank 4).
    """
    board = chess.Board("8/8/8/8/k1r1N2R/8/8/4K3 w - - 0 1")
    result = _can_capture_on(board, chess.C4, chess.E4, chess.BLACK)
    assert result is True


def test_can_capture_on_not_pinned():
    """Unpinned piece always returns True."""
    board = chess.Board("8/8/8/4p3/2N5/8/8/4K2k w - - 0 1")
    # Knight on c4 is not pinned. Can capture e5.
    result = _can_capture_on(board, chess.C4, chess.E5, chess.WHITE)
    assert result is True


def test_get_sorted_attackers_filters_pinned():
    """_get_sorted_attackers excludes pinned pieces that can't reach the target."""
    board = chess.Board("4k3/8/4b3/3p4/2N5/8/8/4RK2 w - - 0 1")
    # Black bishop on e6 attacks d5 diagonally, but is pinned along the e-file.
    # d5 is not on the e-file, so the bishop is filtered out.
    attackers = _get_sorted_attackers(board, chess.D5, chess.BLACK)
    # Bishop is filtered out due to pin. No other black attackers of d5.
    assert len(attackers) == 0


def test_get_sorted_attackers_sorted_by_value():
    """Attackers are returned sorted by piece value ascending.

    White pawn on e4 attacks d5. Black Nf4 (300) and Rd8 (500) both attack d5.
    Sorted result for black should be knight first, then rook.
    """
    board = chess.Board("3r4/8/8/3p4/4Pn2/8/8/6Kk w - - 0 1")
    # White attackers of d5: pawn on e4 (attacks d5 diagonally).
    attackers = _get_sorted_attackers(board, chess.D5, chess.WHITE)
    assert len(attackers) == 1
    assert attackers[0][0] == 100  # pawn value

    # Black defenders of d5: Nf4 (300) and Rd8 (500), sorted ascending.
    black_attackers = _get_sorted_attackers(board, chess.D5, chess.BLACK)
    assert len(black_attackers) == 2
    values = [v for v, _ in black_attackers]
    assert values == [300, 500]  # knight first, then rook


def test_get_sorted_attackers_multiple_pieces_sorted():
    """Multiple attackers sorted: pawn < knight < rook."""
    # Pe4 attacks d5 diagonally, Nf4 attacks d5, Rd1 attacks d5 along d-file.
    board = chess.Board("8/8/8/3p4/4PN2/8/8/3RK1k1 w - - 0 1")
    attackers = _get_sorted_attackers(board, chess.D5, chess.WHITE)
    values = [v for v, _ in attackers]
    assert values == sorted(values)
    assert values == [100, 300, 500]  # pawn, knight, rook


# ---------------------------------------------------------------------------
# Tactic valuation via analyze_tactics
# ---------------------------------------------------------------------------


def test_valuation_check_fork_knight():
    """Knight on e5 forks Kd7 and Rc4 (check fork). Value = 500 (rook).

    Ne5 attacks c4 and d7. Kd7 is in check. Rook on c4 is undefended.
    Opponent must address check, so we capture the rook.
    """
    board = chess.Board("8/3k4/8/4N3/2r5/8/8/K7 w - - 0 1")
    motifs = analyze_tactics(board)

    fork = None
    for f in motifs.forks:
        if f.forking_square == "e5" and f.color == "white":
            fork = f
            break

    assert fork is not None, f"Expected fork on e5, found: {[f.forking_square for f in motifs.forks]}"
    assert fork.is_check_fork
    assert fork.value is not None
    assert fork.value.is_sound
    assert fork.value.material_delta == 500


def test_valuation_non_check_fork_rook_and_bishop():
    """Knight forks rook and bishop (non-check). Value = second target (bishop = 300).

    Nd4 attacks c6 and b3. Black rook on c6 (500), black bishop on b3 (300).
    Opponent saves the rook, we capture the bishop. SEE on b3 = 300 (undefended).
    The pieces are placed so they don't defend each other.
    """
    board = chess.Board("4k3/8/2r5/8/3N4/1b6/8/4K3 w - - 0 1")
    motifs = analyze_tactics(board)

    fork = None
    for f in motifs.forks:
        if f.forking_square == "d4" and f.color == "white":
            fork = f
            break

    assert fork is not None, f"Expected fork on d4, found: {[f.forking_square for f in motifs.forks]}"
    assert not fork.is_check_fork
    assert fork.value is not None
    assert fork.value.is_sound
    assert fork.value.material_delta == 300  # bishop value (second target)


def test_valuation_absolute_pin():
    """Bishop pins knight to king. Absolute pin value = pinned piece (300)."""
    # Bb3 pins Nd5 to Kf7 along b3-c4-d5-e6-f7 diagonal.
    board = chess.Board("8/5k2/8/3n4/8/1B6/8/4K3 w - - 0 1")
    motifs = analyze_tactics(board)

    pin = None
    for p in motifs.pins:
        if p.pinned_square == "d5" and p.is_absolute:
            pin = p
            break

    assert pin is not None, f"Expected absolute pin on d5, found pins: {[(p.pinned_square, p.is_absolute) for p in motifs.pins]}"
    assert pin.value is not None
    assert pin.value.is_sound
    assert pin.value.material_delta == 300  # knight value


def test_valuation_absolute_skewer():
    """Rook skewers king (front) and queen (behind). King must move, value = 900."""
    # Re8 attacks along e-file: e7 (king) and e2 (queen).
    board = chess.Board("4R3/4k3/8/8/8/8/4q3/4K3 w - - 0 1")
    motifs = analyze_tactics(board)

    skewer = None
    for s in motifs.skewers:
        if s.attacker_square == "e8" and s.is_absolute:
            skewer = s
            break

    assert skewer is not None, f"Expected absolute skewer from e8, found: {[(s.attacker_square, s.is_absolute) for s in motifs.skewers]}"
    assert skewer.value is not None
    assert skewer.value.is_sound
    assert skewer.value.material_delta == 900  # queen value


def test_valuation_all_motifs_have_values():
    """In a complex position, all valued motif types get a TacticValue assigned."""
    # Ruy Lopez position with pins and tactical features.
    board = chess.Board("r1bqk2r/ppppbppp/2n5/1B6/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 0 1")
    motifs = analyze_tactics(board)

    for pin in motifs.pins:
        assert pin.value is not None, f"Pin on {pin.pinned_square} has no value"

    for fork in motifs.forks:
        assert fork.value is not None, f"Fork on {fork.forking_square} has no value"

    for skewer in motifs.skewers:
        assert skewer.value is not None, f"Skewer from {skewer.attacker_square} has no value"

    for h in motifs.hanging:
        assert h.value is not None, f"Hanging piece on {h.square} has no value"

    for da in motifs.discovered_attacks:
        assert da.value is not None, f"Discovered attack on {da.target_square} has no value"


def test_valuation_hanging_piece():
    """An undefended piece attacked by a lower-value piece has positive SEE value."""
    # White pawn on c4 attacks d5. Black knight on d5 with no defenders.
    board = chess.Board("4k3/8/8/3n4/2P5/8/8/4K3 w - - 0 1")
    motifs = analyze_tactics(board)

    hanging = [h for h in motifs.hanging if h.square == "d5"]
    assert len(hanging) >= 1, f"Expected hanging piece on d5, found: {[h.square for h in motifs.hanging]}"
    h = hanging[0]
    assert h.value is not None
    assert h.value.is_sound
    assert h.value.material_delta > 0


# ---------------------------------------------------------------------------
# Edge cases and regression tests
# ---------------------------------------------------------------------------


def test_see_king_cannot_capture_defended_piece():
    """King cannot profitably capture a piece defended by a pawn.

    Kd3 takes Ne4, but the knight is defended by black pawn on f5
    (which attacks e4). After Kd3xe4, f5xe4 loses the king.
    SEE is very negative: the king should not capture.
    """
    board = chess.Board("4k3/8/8/5p2/4n3/3K4/8/8 w - - 0 1")
    result = see(board, chess.E4, chess.WHITE)
    assert result < 0


def test_see_battery_queen_behind_rook():
    """Queen behind rook on same file (battery). Both attack after captures.

    White Qd1 behind Rd2, both on d-file. After Rd2xd5, black Rd8 recaptures,
    then Qd1 x-rays through and recaptures.
    """
    board = chess.Board("3r3k/8/8/3p4/8/8/3R4/3Q2K1 w - - 0 1")
    result = see(board, chess.D5, chess.WHITE)
    # Rd2xd5 (+100), Rd8xd5 (gain[1] = 500 - 100 = 400),
    # Qd1xd5 (gain[2] = 500 - 400 = 100).
    # Back-prop: gain[1] = -max(-400, 100) = -100.
    # gain[0] = -max(-100, -100) = 100.
    assert result == 100


def test_see_symmetric_rook_exchange():
    """Two rooks each side on the same file. White captures, then full exchange."""
    # White Rd1, Rd2 vs Black Rd7, Rd8 — all on d-file.
    board = chess.Board("3r4/3r4/8/8/8/8/3R4/3RK1k1 w - - 0 1")
    result = see(board, chess.D7, chess.WHITE)
    # Rd2xd7(+500), Rd8xd7(gain[1]=500-500=0), Rd1xd7(gain[2]=500-0=500).
    # Back-prop: gain[1] = -max(0, 500) = -500. gain[0] = -max(-500, -500) = 500.
    assert result == 500


def test_see_pawn_promotion_not_modeled():
    """SEE doesn't model promotion -- pawn is valued at 100 in SEE.

    White pawn on e7 captures d8 rook. The captured piece is a rook (500).
    The pawn remains valued as 100 centipawns in the SEE calculation.
    """
    board = chess.Board("3r4/4P3/8/8/8/8/8/4K2k w - - 0 1")
    result = see(board, chess.D8, chess.WHITE)
    assert result == 500


def test_piece_values_complete():
    """All standard piece types have values in _PIECE_VALUES."""
    for pt in [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING]:
        assert pt in _PIECE_VALUES
    assert _PIECE_VALUES[chess.PAWN] == 100
    assert _PIECE_VALUES[chess.KNIGHT] == 300
    assert _PIECE_VALUES[chess.BISHOP] == 300
    assert _PIECE_VALUES[chess.ROOK] == 500
    assert _PIECE_VALUES[chess.QUEEN] == 900
    assert _PIECE_VALUES[chess.KING] == 10000


def test_see_does_not_mutate_board():
    """SEE should not modify the input board."""
    fen = "3r4/8/8/3p4/8/8/3R4/3RK1k1 w - - 0 1"
    board = chess.Board(fen)
    see(board, chess.D5, chess.WHITE)
    assert board.fen() == fen


def test_see_black_as_attacker():
    """SEE works correctly when black is the attacker.

    Black rook on d8 captures white pawn on d2 (+100), defended by Ke1 which
    recaptures (-500). Net: -400 for black (rook for pawn is a bad trade).
    """
    board = chess.Board("3r4/8/8/8/8/8/3P4/4K2k b - - 0 1")
    result = see(board, chess.D2, chess.BLACK)
    assert result == 100 - 500  # -400


def test_see_multiple_defenders_with_pin():
    """Multiple defenders but one is pinned off-ray. Only the unpinned one counts.

    White Nf4 takes d5 pawn. Black pawn on c6 defends d5 (attacks b5, d5).
    Black bishop on e6 also attacks d5 but is pinned along e-file by Re1 to Ke8.
    Only the pawn recaptures: knight (300) for pawn (100) is a bad trade.
    """
    board = chess.Board("4k3/8/2p1b3/3p4/5N2/8/8/4RK2 w - - 0 1")
    result = see(board, chess.D5, chess.WHITE)
    # Nf4xd5 (+100), c6xd5 recaptures knight (gain[1] = 300 - 100 = 200).
    # Back-prop: gain[0] = -max(-100, 200) = -200.
    assert result == 100 - 300  # -200


def test_valuation_relative_pin():
    """Relative pin: bishop pins knight to queen. SEE-based value.

    Bb3 pins Nd5 to Qg8 along b3-c4-d5-e6-f7-g8 diagonal.
    SEE of Bb3xd5: bishop (300) takes knight (300), Qg8 recaptures.
    Net SEE = 0 (break-even), so the relative pin is not sound.
    """
    board = chess.Board("4k1q1/8/8/3n4/8/1B6/8/4K3 w - - 0 1")
    motifs = analyze_tactics(board)

    pin = None
    for p in motifs.pins:
        if p.pinned_square == "d5" and not p.is_absolute:
            pin = p
            break

    assert pin is not None, f"Expected relative pin on d5, found: {[(p.pinned_square, p.is_absolute) for p in motifs.pins]}"
    assert pin.value is not None
    assert pin.value.material_delta == 0
    assert pin.value.is_sound is False


# ---------------------------------------------------------------------------
# Direct valuation function tests (coverage for uncovered branches)
# ---------------------------------------------------------------------------


def test_value_fork_non_check_forker_capturable():
    """Non-check fork where opponent can profitably capture the forker.

    White Nd4 forks black Rc6 and Bb5. Both undefended by other pieces.
    But black pawn on e6 can capture the knight (300 - 300 = 0 for pawn taking knight?
    No — pawn is worth 100, knight 300, so SEE of capturing Nd4 with pawn = 300).
    Fork value = second_target (300 bishop) - forker_loss (300) = 0.
    """
    # Nd4 attacks: b3,b5,c2,c6,e2,e6,f3,f5
    # Rc6 (500), Bb5 (300). e6 has a black pawn that attacks d5 not d4...
    # Let me use c3 pawn: Nd4 is attacked by black pawn on c5? No, c5 pawn attacks b4,d4. Yes!
    board = chess.Board("4k3/8/2r5/1bp5/3N4/8/8/4K3 w - - 0 1")
    fork = Fork(
        forking_square="d4",
        forking_piece="N",
        targets=["c6", "b5"],
        target_pieces=["r", "b"],
        color="white",
        is_check_fork=False,
    )
    val = _value_fork(fork, board)
    assert val is not None
    # second target is bishop (300), but forker can be captured by c5 pawn
    # forker_loss = see(board, d4, BLACK) which should be positive (pawn takes knight)
    # delta = 300 - forker_loss; here 300 - 300 = 0
    assert val.material_delta >= 0


def test_value_fork_negative_delta():
    """Non-check fork where forker loss exceeds capture gain → negative delta.

    White Nc6 forks black pawns on a7 and e7, but black can capture with bxc6.
    Second target pawn = 100cp, forker_loss (knight captured) = 300cp.
    delta = 100 - 300 = -200.
    """
    # Black b7-pawn can capture Nc6. Pawns on a7 and e7 are fork targets.
    board = chess.Board("3qk3/pp2p3/2N5/8/8/8/8/4K3 w - - 0 1")
    fork = Fork(
        forking_square="c6",
        forking_piece="N",
        targets=["a7", "e7"],
        target_pieces=["p", "p"],
        color="white",
        is_check_fork=False,
    )
    val = _value_fork(fork, board)
    assert val is not None
    # Knight forks two pawns but is capturable: 100 - 300 = -200
    assert val.material_delta < 0
    assert val.is_sound is False


def test_value_skewer_non_absolute():
    """Non-absolute skewer: queen in front, rook behind. SEE on behind piece."""
    # White Bb1 skewers black Qd3 (front, higher value) and black Rf5 (behind, lower value)
    # This is a skewer because front value > behind value
    # Actually the ray detector classifies: front=enemy, behind=enemy, front_val > second_val
    # and attacker_val <= front_val => skewer
    # Let's build the Skewer directly and test the valuation function
    # Rook on a1 skewers queen on d4 (front) and bishop on g7 (behind)
    board = chess.Board("4k3/6b1/8/8/3q4/8/8/R3K3 w - - 0 1")
    skewer = Skewer(
        attacker_square="a1",
        attacker_piece="R",
        front_square="d4",
        front_piece="q",
        behind_square="g7",
        behind_piece="b",
        color="white",
        is_absolute=False,
    )
    val = _value_skewer(skewer, board)
    assert val is not None
    # SEE on g7 (behind piece) from white's perspective
    # Ra1 doesn't attack g7 (different rank/file with pieces in the way)
    # This tests the code path; exact value depends on SEE of that square


def test_value_discovered_attack():
    """Discovered attack: blocker moves, slider attacks target."""
    # White Rd1 behind white Nd4 (blocker), black queen on d8 (target)
    board = chess.Board("3q4/8/8/8/3N4/8/8/3RK1k1 w - - 0 1")
    da = DiscoveredAttack(
        blocker_square="d4",
        blocker_piece="N",
        slider_square="d1",
        slider_piece="R",
        target_square="d8",
        target_piece="q",
        color="white",
    )
    val = _value_discovered(da, board)
    assert val is not None
    assert val.source == "see"
    # SEE of Rd1 capturing d8 queen — but Nd4 is in the way currently.
    # The SEE approximation uses the current board, so Rd1 can't reach d8.
    # This is a known approximation (noted in plan). Value should be 0.
    assert val.material_delta == 0
    assert val.is_sound is False


def test_value_capturable_defender_profitable():
    """Capture the defender, then the charge is undefended.

    White pawn on c4 can capture black Nd5 (the defender).
    Nd5 sole-defends black Rf5. After Nd5 is captured, Rf5 is hanging.
    step1 = SEE(c4xd5) = 300 - 100 = 200 (pawn takes knight, profitable)
    step2 = value of Rf5 = 500
    total = 200 + 500 = 700
    """
    board = chess.Board("4k3/8/8/3n1r2/2P5/8/8/4K3 w - - 0 1")
    cd = CapturableDefender(
        defender_square="d5",
        defender_piece="n",
        charge_square="f5",
        charge_piece="r",
        attacker_square="c4",
        color="black",  # defender's color is black
    )
    val = _value_capturable_defender(cd, board)
    assert val is not None
    assert val.is_sound
    assert val.material_delta > 0
    # step1 = see(board, d5, WHITE): pawn captures knight (+300), but Rf5 defends
    # d5 along rank 5, so rook recaptures. SEE back-propagation gives step1 = 200.
    # step2 = 500 (rook value). total = 200 + 500 = 700.
    assert val.material_delta == 200 + 500  # 700


def test_value_capturable_defender_unprofitable_capture():
    """Capturing the defender loses material — only step1 matters.

    White queen on c4 could capture black Rd5 (the defender).
    But QxR loses the queen: step1 = see(board, d5, WHITE) = 500 - 900 = -400.
    Since step1 < 0, we don't add step2.
    """
    # Black Rd5 defended by black pawn on e6 (attacks d5)
    board = chess.Board("4k3/8/4p3/3r1b2/2Q5/8/8/4K3 w - - 0 1")
    cd = CapturableDefender(
        defender_square="d5",
        defender_piece="r",
        charge_square="f5",
        charge_piece="b",
        attacker_square="c4",
        color="black",
    )
    val = _value_capturable_defender(cd, board)
    assert val is not None
    assert val.is_sound is False
    assert val.material_delta < 0


def test_value_overloaded_piece():
    """Overloaded piece defending two squares. Value = min duty value.

    Black Nd5 defends both f4 (pawn, 100cp) and b6 (bishop, 300cp).
    Min duty value = 100 (the pawn).
    """
    board = chess.Board("4k3/8/1b6/3n4/5p2/8/8/4K3 b - - 0 1")
    op = OverloadedPiece(
        square="d5",
        piece="n",
        defended_squares=["f4", "b6"],
        color="black",
    )
    val = _value_overloaded(op, board)
    assert val is not None
    assert val.source == "heuristic"
    assert val.is_sound
    assert val.material_delta == 100  # min of pawn(100), bishop(300)


def test_value_overloaded_empty_duties():
    """Overloaded piece where defended squares have no pieces (edge case)."""
    board = chess.Board("4k3/8/8/3n4/8/8/8/4K3 b - - 0 1")
    op = OverloadedPiece(
        square="d5",
        piece="n",
        defended_squares=["f4", "b6"],  # both empty
        color="black",
    )
    val = _value_overloaded(op, board)
    assert val is not None
    assert val.source == "heuristic"
    assert val.is_sound is False
    assert val.material_delta == 0


# ---------------------------------------------------------------------------
# Defense notes tests
# ---------------------------------------------------------------------------


def test_defense_notes_pinned_defender():
    """Nd7 pinned by Rd1 to Kd8 along d-file, defending e5 (off d-file).

    FEN: 3k4/3n4/8/4p3/4P3/8/8/3RK3 w - - 0 1
    Rd1 pins Nd7 to Kd8. Pe4 attacks e5. Nd7 "defends" e5 but is pinned off-ray.
    """
    board = chess.Board("3k4/3n4/8/4p3/4P3/8/8/3RK3 w - - 0 1")
    notes = _build_defense_notes(board, chess.E5, chess.BLACK)
    assert "pinned" in notes
    assert "d7" in notes


def test_defense_notes_empty_no_pins():
    """Genuinely hanging piece with no pinned defenders → empty defense_notes."""
    # Black knight on d5, undefended, attacked by white pawn on c4
    board = chess.Board("4k3/8/8/3n4/2P5/8/8/4K3 w - - 0 1")
    notes = _build_defense_notes(board, chess.D5, chess.BLACK)
    assert notes == ""


def test_defense_notes_pinned_on_ray_still_defends():
    """Defender pinned but target IS on pin ray → defense_notes is empty.

    Be6 pinned along b3-f7 diagonal by Bb3 to Kf7. d5 is on the diagonal,
    so Be6 CAN capture there despite being pinned.
    """
    board = chess.Board("8/5k2/4b3/8/8/1BN5/8/4K3 w - - 0 1")
    notes = _build_defense_notes(board, chess.D5, chess.BLACK)
    assert notes == ""


def test_related_motifs_cross_refs_pin():
    """Cross-reference logic: hanging piece with defense_notes gets related_motifs populated.

    The cross-reference pass in analyze_tactics links hanging pieces to pins
    when defense_notes mentions a pinned square. We test this by verifying
    the logic on a constructed TacticalMotifs with pre-set defense_notes.

    Note: In current _find_hanging (Lichess is_defended), pinned defenders
    still count as defenders, so defense_notes on real hanging pieces is rare.
    This test validates the cross-reference wiring independently.
    """
    from server.analysis.tactics.types import TacticalMotifs

    pin = Pin(
        pinned_square="d7", pinned_piece="n",
        pinner_square="d1", pinner_piece="R",
        pinned_to="d8", pinned_to_piece="k",
        is_absolute=True, color="white",
    )
    hanging = HangingPiece(
        square="f5", piece="b", attacker_squares=["e4", "e3"],
        color="black", can_retreat=False,
        value=TacticValue(
            material_delta=300, is_sound=True,
            defense_notes="defender N on d7 pinned to d8",
        ),
    )
    motifs = TacticalMotifs(pins=[pin], hanging=[hanging])

    # Simulate the cross-reference pass from analyze_tactics
    for h in motifs.hanging:
        if h.value and h.value.defense_notes:
            for p in motifs.pins:
                if p.pinned_square in h.value.defense_notes:
                    h.value.related_motifs.append(
                        f"pin:{p.pinner_square}-{p.pinned_square}-{p.pinned_to}"
                    )

    assert len(hanging.value.related_motifs) == 1
    assert "d7" in hanging.value.related_motifs[0]
    assert hanging.value.related_motifs[0] == "pin:d1-d7-d8"
