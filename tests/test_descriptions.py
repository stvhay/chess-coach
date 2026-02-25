"""Tests for descriptions.py — tactic diffing, describe functions."""

import chess

from server.analysis import (
    DiscoveredAttack,
    Fork,
    HangingPiece,
    Pin,
    TacticalMotifs,
)
from server.analysis import analyze
from server.descriptions import (
    PositionDescription,
    _blocker_is_move_dest,
    _to_past_tense,
    diff_tactics,
    describe_changes,
    describe_position,
    describe_position_from_report,
    _should_skip_back_rank,
)
from server.game_tree import GameNode, GameTree


# --- Tactic diffing tests ---

class TestTacticDiff:
    def test_empty_to_pin(self):
        """Parent has no tactics, child has a pin → pin is new."""
        parent = TacticalMotifs()
        child = TacticalMotifs(pins=[
            Pin("N", "c6", "B", "b5", "e8", "k", True)
        ])
        diff = diff_tactics(parent, child)
        assert len(diff.new_keys) == 1
        assert len(diff.resolved_keys) == 0

    def test_pin_resolved(self):
        """Parent has a pin, child doesn't → pin resolved."""
        pin = Pin("N", "c6", "B", "b5", "e8", "k", True)
        parent = TacticalMotifs(pins=[pin])
        child = TacticalMotifs()
        diff = diff_tactics(parent, child)
        assert len(diff.resolved_keys) == 1
        assert len(diff.new_keys) == 0

    def test_same_pin_persists(self):
        """Same pin in both → persistent, not new or resolved."""
        pin = Pin("N", "c6", "B", "b5", "e8", "k", True)
        parent = TacticalMotifs(pins=[pin])
        child = TacticalMotifs(pins=[pin])
        diff = diff_tactics(parent, child)
        assert len(diff.persistent_keys) == 1
        assert len(diff.new_keys) == 0
        assert len(diff.resolved_keys) == 0

    def test_fork_new_and_pin_resolved(self):
        """Pin resolved and fork appears."""
        pin = Pin("N", "c6", "B", "b5", "e8", "k", True)
        fork = Fork("f7", "N", ["e8", "h8"])
        parent = TacticalMotifs(pins=[pin])
        child = TacticalMotifs(forks=[fork])
        diff = diff_tactics(parent, child)
        assert len(diff.new_keys) == 1
        assert len(diff.resolved_keys) == 1


# --- describe_position tests ---

def test_describe_position_returns_structured():
    """describe_position produces a PositionDescription."""
    root = GameNode(board=chess.Board(), source="played")
    tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
    desc = describe_position(tree, root)
    assert isinstance(desc, PositionDescription)
    assert isinstance(desc.threats, list)
    assert isinstance(desc.opportunities, list)
    assert isinstance(desc.observations, list)


# --- describe_changes tests ---

def test_describe_changes_no_parent():
    """Root node returns empty 3-tuple."""
    root = GameNode(board=chess.Board(), source="played")
    tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
    opps, thrs, obs = describe_changes(tree, root)
    assert opps == []
    assert thrs == []
    assert obs == []


def test_describe_changes_with_pin():
    """Position where Nc3 creates a pin should report pin in changes."""
    # After 1.d4 e5 2.dxe5 Bb4+ — student plays Nc3 getting pinned
    fen = "rnbqk1nr/pppp1ppp/8/4P3/1b6/8/PPP1PPPP/RNBQKBNR w KQkq - 1 3"
    board_before = chess.Board(fen)
    root = GameNode(board=board_before, source="played")

    # Play Nc3
    move = chess.Move.from_uci("b1c3")
    child = root.add_child(move, "played")

    tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
    opps, thrs, obs = describe_changes(tree, child)

    # The pin should appear in the output (as threat since student's piece gets pinned)
    all_text = " ".join(opps + thrs + obs).lower()
    assert "pin" in all_text


def test_back_rank_filtered_early_game():
    """Starting position should have no back rank observations (both uncastled, move < 10)."""
    root = GameNode(board=chess.Board(), source="played")
    tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
    desc = describe_position(tree, root)
    all_text = " ".join(desc.observations).lower()
    assert "back rank" not in all_text


# --- describe_position_from_report tests ---

def test_describe_position_from_report_returns_structured():
    """describe_position_from_report produces a PositionDescription."""
    report = analyze(chess.Board())
    desc = describe_position_from_report(report, student_is_white=True)
    assert isinstance(desc, PositionDescription)
    assert isinstance(desc.threats, list)
    assert isinstance(desc.opportunities, list)
    assert isinstance(desc.observations, list)


def test_describe_position_from_report_matches_describe_position():
    """describe_position_from_report should match describe_position output."""
    root = GameNode(board=chess.Board(), source="played")
    tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
    desc_tree = describe_position(tree, root)
    desc_report = describe_position_from_report(root.report, student_is_white=True)
    assert desc_tree.threats == desc_report.threats
    assert desc_tree.opportunities == desc_report.opportunities
    assert desc_tree.observations == desc_report.observations


# --- as_text tests ---

def test_as_text_empty():
    """Empty PositionDescription returns balanced message."""
    desc = PositionDescription()
    assert "balanced" in desc.as_text().lower()


def test_as_text_with_items():
    """as_text joins and caps items."""
    desc = PositionDescription(
        threats=["threat1", "threat2"],
        opportunities=["opp1"],
        observations=["obs1"],
    )
    text = desc.as_text()
    assert "threat1" in text
    assert "opp1" in text
    assert "obs1" in text


def test_as_text_max_items():
    """as_text respects max_items."""
    desc = PositionDescription(
        threats=[f"t{i}" for i in range(10)],
    )
    text = desc.as_text(max_items=3)
    assert "t0" in text
    assert "t2" in text
    assert "t3" not in text


# --- Past tense conversion tests ---


class TestToPastTense:
    """Test the present-to-past tense conversion function."""

    # --- Motif verb forms ---

    def test_forks(self):
        assert _to_past_tense("Your knight on e5 forks their rook.") == \
            "Your knight on e5 forked their rook."

    def test_pins(self):
        assert _to_past_tense("Your bishop on b5 pins their knight on c6 to their king.") == \
            "Your bishop on b5 pinned their knight on c6 to their king."

    def test_pins_and_also_attacks(self):
        assert _to_past_tense("Your rook pins and also attacks their queen.") == \
            "Your rook pinned and also attacked their queen."

    def test_skewers(self):
        assert _to_past_tense("Your bishop on a4 skewers their queen.") == \
            "Your bishop on a4 skewered their queen."

    def test_is_undefended(self):
        assert _to_past_tense("Their pawn on e4 is undefended.") == \
            "Their pawn on e4 was undefended."

    def test_is_hanging(self):
        assert _to_past_tense("Their knight on f6 is hanging.") == \
            "Their knight on f6 was hanging."

    def test_is_trapped(self):
        assert _to_past_tense("Their bishop on h7 is trapped.") == \
            "Their bishop on h7 was trapped."

    def test_is_weak(self):
        assert _to_past_tense("Their back rank is weak (king on g8).") == \
            "Their back rank was weak (king on g8)."

    def test_is_exposed(self):
        assert _to_past_tense("Their king on e5 is exposed (advanced, no pawn shield).") == \
            "Their king on e5 was exposed (advanced, no pawn shield)."

    def test_is_overloaded(self):
        assert _to_past_tense("Their knight on c3 is overloaded, sole defender of e4, d5.") == \
            "Their knight on c3 was overloaded, sole defender of e4, d5."

    def test_threatens_checkmate(self):
        assert _to_past_tense("You threaten checkmate on h7.") == \
            "You threatened checkmate on h7."
        assert _to_past_tense("They threaten checkmate on h2.") == \
            "They threatened checkmate on h2."

    def test_defends(self):
        assert _to_past_tense("Their rook on d1 defends their pawn on d5") == \
            "Their rook on d1 defended their pawn on d5"

    def test_is_left_hanging(self):
        assert _to_past_tense("if captured, their pawn on d5 is left hanging.") == \
            "if captured, their pawn on d5 was left hanging."

    def test_double_check(self):
        """Double check from X — noun phrase, no verb to convert."""
        text = "Double check from e5 and c3."
        assert _to_past_tense(text) == text

    def test_xrays_through(self):
        assert _to_past_tense("Your rook on a1 x-rays through their knight.") == \
            "Your rook on a1 x-rayed through their knight."

    def test_discovered_xray_alignment(self):
        """X-ray alignment (position mode) — noun phrase, no verb."""
        text = "X-ray alignment: your bishop on c4 behind their pawn on d5 toward their king on e8."
        assert _to_past_tense(text) == text

    def test_discovered_attack_conditional(self):
        """Discovered attack uses conditional tense — no conversion needed."""
        text = "If your knight on f3 moves, your bishop on c4 will target their queen on d5."
        assert _to_past_tense(text) == text

    def test_controls_diagonal(self):
        assert _to_past_tense("White's bishop on g2 controls the a8-h1 diagonal.") == \
            "White's bishop on g2 controlled the a8-h1 diagonal."

    # --- Positional observation verb forms ---

    def test_is_in_check(self):
        assert _to_past_tense("Black is in check.") == "Black was in check."

    def test_is_up_material(self):
        assert _to_past_tense("White is up approximately 3 points of material.") == \
            "White was up approximately 3 points of material."

    def test_has_isolated_pawns(self):
        assert _to_past_tense("White has isolated pawns on c3, e4.") == \
            "White had isolated pawns on c3, e4."

    def test_has_passed_pawns(self):
        assert _to_past_tense("Black has passed pawns on d4.") == \
            "Black had passed pawns on d4."

    def test_king_has_open_files(self):
        assert _to_past_tense("White's king has open files nearby.") == \
            "White's king had open files nearby."

    def test_king_is_actively_placed(self):
        assert _to_past_tense("Black's king is actively placed on d4.") == \
            "Black's king was actively placed on d4."

    def test_has_not_fully_developed(self):
        assert _to_past_tense("White has not fully developed minor pieces.") == \
            "White had not fully developed minor pieces."

    def test_occupies_seventh(self):
        assert _to_past_tense("Rook on d7 occupies the 7th rank.") == \
            "Rook on d7 occupied the 7th rank."

    def test_rooks_are_connected(self):
        assert _to_past_tense("White's rooks are connected on d1, e1.") == \
            "White's rooks were connected on d1, e1."

    def test_has_a_weak_square_complex(self):
        assert _to_past_tense("White has a weak dark-square complex (no dark-squared bishop, pawns on light squares).") == \
            "White had a weak dark-square complex (no dark-squared bishop, pawns on light squares)."

    # --- Passthrough / no-op ---

    def test_empty_string(self):
        assert _to_past_tense("") == ""

    def test_no_match_passes_through(self):
        text = "Checkmate."
        assert _to_past_tense(text) == text

    def test_cannot_move_unchanged(self):
        """The '— it cannot move' suffix should stay unchanged (modal verb)."""
        text = "Your bishop pins their knight on c6 to their king — it cannot move."
        result = _to_past_tense(text)
        assert "pinned" in result
        assert "cannot move" in result


class TestDescribePositionTense:
    """Test that describe_position respects the tense parameter."""

    def test_default_tense_is_present(self):
        """Default (no tense arg) returns present tense — backward compatible."""
        root = GameNode(board=chess.Board(), source="played")
        tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
        desc = describe_position(tree, root)
        all_text = " ".join(desc.threats + desc.opportunities + desc.observations)
        # Should NOT contain past-tense markers
        assert "was " not in all_text or "was" not in all_text.split()

    def test_past_tense_converts_observations(self):
        """tense='past' should convert positional observations to past tense."""
        # Use a position with material imbalance to guarantee an observation
        # White up a queen: White Ke1, Qd1; Black Ke8
        board = chess.Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
        root = GameNode(board=board, source="played")
        tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
        desc = describe_position(tree, root, tense="past")
        all_obs = " ".join(desc.observations)
        # Material observation should use past tense
        assert "was up approximately" in all_obs or "had" in all_obs

    def test_present_tense_explicit(self):
        """tense='present' returns present tense (same as default)."""
        board = chess.Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
        root = GameNode(board=board, source="played")
        tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
        desc_default = describe_position(tree, root)
        desc_present = describe_position(tree, root, tense="present")
        assert desc_default.threats == desc_present.threats
        assert desc_default.opportunities == desc_present.opportunities
        assert desc_default.observations == desc_present.observations


# --- key-level filtering regression tests ---


def test_describe_changes_no_duplicate_persistent_motifs():
    """Persistent motifs should not be re-rendered when a new motif of the same type appears.

    Regression test: _new_motif_types collapsed keys to types, causing ALL
    items of a type to render when only some were new.
    """
    # Parent has fork A
    fork_a = Fork("d5", "N", ["c3", "f6"], target_pieces=["B", "R"])
    parent_tactics = TacticalMotifs(forks=[fork_a])

    # Child has fork A (persistent) + fork B (new)
    fork_b = Fork("e4", "N", ["c5", "g5"], target_pieces=["B", "Q"])
    child_tactics = TacticalMotifs(forks=[fork_a, fork_b])

    # Build a minimal tree with mocked tactics
    parent_board = chess.Board()
    parent_node = GameNode(board=parent_board, source="played")

    move = chess.Move.from_uci("g1f3")
    child_node = parent_node.add_child(move, "played")

    tree = GameTree(
        root=parent_node, decision_point=parent_node, player_color=chess.WHITE,
    )

    # Patch tactics caches directly
    parent_node._tactics = parent_tactics
    child_node._tactics = child_tactics

    opps, thrs, obs = describe_changes(tree, child_node)
    all_text = " ".join(opps + thrs + obs).lower()

    # Fork B (e4) should appear
    assert "e4" in all_text, "New fork on e4 should be described"
    # Fork A (d5) should NOT appear — it was persistent, not new
    assert "d5" not in all_text, "Persistent fork on d5 should NOT be re-rendered"


# --- False discovered attack tests (Bug #8) ---


class TestFalseDiscoveredAttack:
    """Bug #8: piece moving ONTO a ray reports false 'discovered attack'."""

    def test_blocker_is_move_dest_helper(self):
        """_blocker_is_move_dest returns True when blocker == move dest."""
        da = DiscoveredAttack(
            blocker_square="f6", blocker_piece="B",
            slider_square="d4", slider_piece="Q",
            target_square="g7", target_piece="p",
        )
        tactics = TacticalMotifs(discovered_attacks=[da])
        key = ("discovered", "d4", "g7")
        assert _blocker_is_move_dest(key, tactics, "f6") is True

    def test_blocker_is_move_dest_false_for_other_square(self):
        """_blocker_is_move_dest returns False when blocker != move dest."""
        da = DiscoveredAttack(
            blocker_square="e5", blocker_piece="N",
            slider_square="d4", slider_piece="Q",
            target_square="g7", target_piece="p",
        )
        tactics = TacticalMotifs(discovered_attacks=[da])
        key = ("discovered", "d4", "g7")
        assert _blocker_is_move_dest(key, tactics, "f6") is False

    def test_blocker_is_move_dest_non_discovered_key(self):
        """_blocker_is_move_dest returns False for non-discovered keys."""
        tactics = TacticalMotifs()
        key = ("pin", "b5", "e8")
        assert _blocker_is_move_dest(key, tactics, "c6") is False

    def test_false_discovered_attack_blocker_arrives(self):
        """Piece moves ONTO ray → discovered attack is suppressed in describe_changes.

        Scenario: White Qd4, Black pawns g7/h6. Move: Bxf6 (bishop lands
        on the d4→g7 ray). The after-position has a DiscoveredAttack with
        blocker=f6, but the bishop just arrived there — nothing was "discovered".
        """
        # Parent: White Qd4, Bg5; Black Nf6, pawns g7/h6
        parent_board = chess.Board("4k3/6p1/5n1p/6B1/3Q4/8/8/4K3 w - - 0 1")
        parent_node = GameNode(board=parent_board, source="played")

        # Move: Bxf6 (bishop captures on f6, landing on d4-g7 ray)
        move = chess.Move.from_uci("g5f6")
        child_node = parent_node.add_child(move, "played")

        # Patch tactics: parent has no discovered attacks, child has one
        # where the blocker (f6) is the move destination
        parent_node._tactics = TacticalMotifs()
        child_node._tactics = TacticalMotifs(discovered_attacks=[
            DiscoveredAttack(
                blocker_square="f6", blocker_piece="B",
                slider_square="d4", slider_piece="Q",
                target_square="g7", target_piece="p",
                color="white",
            ),
        ])

        tree = GameTree(
            root=parent_node, decision_point=parent_node,
            player_color=chess.WHITE,
        )
        opps, thrs, obs = describe_changes(tree, child_node)
        all_text = " ".join(opps + thrs + obs).lower()
        assert "discover" not in all_text, \
            "False discovered attack (blocker arrived at square) should be suppressed"

    def test_genuine_discovered_attack_preserved(self):
        """Blocker was already there → discovered attack is preserved.

        Scenario: White Rb1, Na4; Black Qa8. Move: Ra1 (rook slides to a1,
        creating Ra1-Na4-Qa8 alignment). The blocker Na4 was NOT the piece
        that moved, so the discovered attack should survive filtering.
        """
        parent_board = chess.Board("q3k3/8/8/8/N7/8/8/1R2K3 w - - 0 1")
        parent_node = GameNode(board=parent_board, source="played")

        # Move: Rb1-a1 (rook moves, knight is already on a4)
        move = chess.Move.from_uci("b1a1")
        child_node = parent_node.add_child(move, "played")

        # Patch tactics: child has discovered attack with blocker=a4 (the knight)
        parent_node._tactics = TacticalMotifs()
        child_node._tactics = TacticalMotifs(discovered_attacks=[
            DiscoveredAttack(
                blocker_square="a4", blocker_piece="N",
                slider_square="a1", slider_piece="R",
                target_square="a8", target_piece="q",
                color="white",
            ),
        ])

        tree = GameTree(
            root=parent_node, decision_point=parent_node,
            player_color=chess.WHITE,
        )
        opps, thrs, obs = describe_changes(tree, child_node)
        all_text = " ".join(opps + thrs + obs).lower()
        # The discovered attack should be preserved (blocker a4 != move dest a1)
        assert "discover" in all_text or "x-ray" in all_text or "a4" in all_text, \
            "Genuine discovered attack (blocker already in place) should be preserved"


# --- Bug 2: re-emerging motif tests ---


def test_remerging_motif_reported():
    """Bug 2 fix: motif suppressed at ply 0 should not block future rendering.

    With the old code, seen_motif_keys was updated via all_tactic_keys(),
    which added ALL motifs from each position — including ones that were
    not rendered (e.g., suppressed by fork-implies-hanging dedup). This
    blocked those motifs from being reported when they reappeared later.

    Scenario (3-ply chain):
    - Parent: no tactics
    - Ply 0: fork on c6 + hanging on c6 (hanging suppressed by fork dedup)
    - Ply 1: fork and hanging both disappear
    - Ply 2: hanging on c6 reappears (alone, no fork)

    Old behavior: all_tactic_keys(ply0) adds hanging's key to seen_motif_keys
    even though it was never rendered (suppressed by fork dedup). At ply 2,
    hanging is filtered out.

    Fixed behavior: rendered_keys from ply 0 does NOT contain hanging (it was
    suppressed). At ply 2, hanging is not in seen_motif_keys, so it's reported.
    """
    parent_board = chess.Board()
    parent_node = GameNode(board=parent_board, source="played")

    move0 = chess.Move.from_uci("g1f3")
    ply0 = parent_node.add_child(move0, "played")

    move1 = chess.Move.from_uci("b8c6")
    ply1 = ply0.add_child(move1, "engine")

    move2 = chess.Move.from_uci("f3e5")
    ply2 = ply1.add_child(move2, "engine")

    # Fork on d5 targeting c6 and g6 — hanging on c6 will be suppressed
    fork = Fork("d5", "N", ["c6", "g6"], ["r", "q"])
    hanging = HangingPiece(square="c6", piece="r", attacker_squares=["d5"], color="Black")

    # Parent: no tactics
    parent_node._tactics = TacticalMotifs()
    # Ply 0: fork + hanging (hanging suppressed by fork-implies-hanging dedup)
    ply0._tactics = TacticalMotifs(forks=[fork], hanging=[hanging])
    # Ply 1: everything disappears
    ply1._tactics = TacticalMotifs()
    # Ply 2: hanging reappears alone (no fork to suppress it)
    ply2._tactics = TacticalMotifs(hanging=[hanging])

    tree = GameTree(
        root=parent_node, decision_point=parent_node, player_color=chess.WHITE,
    )
    opps, thrs, obs = describe_changes(tree, ply0, max_plies=3)
    all_text = " ".join(opps + thrs + obs).lower()

    # The hanging piece at ply 2 should be reported
    assert "hanging" in all_text or "undefended" in all_text, (
        f"Re-emerging hanging piece on c6 should be reported at ply 2, "
        f"but was not found in: {all_text}"
    )
