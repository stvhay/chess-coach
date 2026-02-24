"""Tests for descriptions.py — tactic diffing, describe functions."""

import chess

from server.analysis import (
    Fork,
    Pin,
    TacticalMotifs,
)
from server.analysis import analyze
from server.descriptions import (
    PositionDescription,
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
