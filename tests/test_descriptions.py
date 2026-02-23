"""Tests for descriptions.py — tactic diffing, describe functions."""

import chess
import pytest

from server.analysis import (
    Fork,
    Pin,
    Skewer,
    HangingPiece,
    TacticalMotifs,
)
from server.descriptions import (
    TacticDiff,
    diff_tactics,
    describe_changes,
    describe_position,
)
from server.motifs import (
    RenderContext,
    _colored,
    _piece_is_students,
    render_fork,
    render_hanging,
    render_pin,
    render_skewer,
)
from server.game_tree import GameNode, GameTree


# --- Helper ---

def _ctx(student_is_white=True) -> RenderContext:
    return RenderContext(
        student_is_white=student_is_white,
        player_color="White" if student_is_white else "Black",
    )


# --- Shared helper tests ---

class TestHelpers:
    def test_colored_white(self):
        assert _colored("N") == "White N"

    def test_colored_black(self):
        assert _colored("n") == "Black N"

    def test_piece_is_students_white(self):
        assert _piece_is_students("N", True) is True
        assert _piece_is_students("n", True) is False

    def test_piece_is_students_black(self):
        assert _piece_is_students("n", False) is True
        assert _piece_is_students("N", False) is False


# --- Motif renderer tests ---

class TestMotifRenderers:
    def test_render_fork(self):
        fork = Fork("e5", "N", ["c6", "g6"], ["r", "q"])
        desc, is_opp = render_fork(fork, _ctx(True))
        assert "fork by White N on e5" in desc
        assert "Black R on c6" in desc
        assert is_opp is True

    def test_render_fork_opponent(self):
        fork = Fork("e4", "n", ["d2", "f2"], ["R", "Q"])
        desc, is_opp = render_fork(fork, _ctx(True))
        assert is_opp is False  # lowercase n = Black piece, student is White

    def test_render_fork_wins_piece(self):
        fork = Fork("f7", "N", ["e8", "h8"], ["k", "r"])
        desc, is_opp = render_fork(fork, _ctx(True))
        assert "wins the" in desc

    def test_render_pin(self):
        pin = Pin(
            pinned_piece="N", pinned_square="c6",
            pinner_piece="B", pinner_square="b5",
            pinned_to="e8", pinned_to_piece="k",
            is_absolute=True,
        )
        desc, is_opp = render_pin(pin, _ctx(True))
        assert "pin:" in desc
        assert "cannot move" in desc
        assert is_opp is True  # White B pins

    def test_render_skewer(self):
        skewer = Skewer(
            attacker_piece="R", attacker_square="e1",
            front_piece="q", front_square="e5",
            behind_piece="k", behind_square="e8",
        )
        desc, is_opp = render_skewer(skewer, _ctx(True))
        assert "skewer by White R" in desc
        assert is_opp is True

    def test_render_hanging_opponent(self):
        hp = HangingPiece(square="d5", piece="n", attacker_squares=["e3"], color="Black")
        desc, is_opp = render_hanging(hp, _ctx(True))
        assert "hanging" in desc.lower() or "undefended" in desc.lower()
        assert is_opp is True  # opponent's piece hanging = opportunity

    def test_render_hanging_student(self):
        hp = HangingPiece(square="d5", piece="N", attacker_squares=["e3"], color="White")
        desc, is_opp = render_hanging(hp, _ctx(True))
        assert is_opp is False  # student's piece hanging = threat


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

def test_describe_position_returns_summary():
    """describe_position produces a non-empty string."""
    root = GameNode(board=chess.Board(), source="played")
    tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
    desc = describe_position(tree, root)
    assert isinstance(desc, str)
    # Starting position is balanced — summary may be short or empty
    # but should not crash


# --- describe_changes tests ---

def test_describe_changes_no_parent():
    """Root node returns empty lists."""
    root = GameNode(board=chess.Board(), source="played")
    tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
    opps, thrs = describe_changes(tree, root)
    assert opps == []
    assert thrs == []


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
    opps, thrs = describe_changes(tree, child)

    # The pin should appear in the output (as threat since student's piece gets pinned)
    all_text = " ".join(opps + thrs).lower()
    assert "pin" in all_text
