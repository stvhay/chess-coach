"""Tests for report.py — serialize_report section structure and content."""

import chess
import pytest

from server.analysis import MaterialCount
from server.game_tree import GameNode, GameTree
from server.report import (
    _describe_capture,
    _describe_result,
    _format_numbered_move,
    _format_pv_with_numbers,
    _game_pgn,
    _piece_diff,
    serialize_report,
)


# --- Helper functions ---

def _simple_tree(
    player_move_uci: str = "e2e4",
    alt_uci: str = "d2d4",
    player_cp: int = 20,
    alt_cp: int = 30,
) -> GameTree:
    """Build a simple tree: root (starting pos), player + alternative at decision_point."""
    root = GameNode(board=chess.Board(), source="played")
    # Player's move
    pm = chess.Move.from_uci(player_move_uci)
    root.add_child(pm, "played", score_cp=player_cp)
    # Alternative
    am = chess.Move.from_uci(alt_uci)
    root.add_child(am, "engine", score_cp=alt_cp)
    return GameTree(root=root, decision_point=root, player_color=chess.WHITE)


def _tree_with_history() -> GameTree:
    """Tree with 1.e4 e5 history, decision at move 2 (White to move)."""
    root = GameNode(board=chess.Board(), source="played")
    e4 = root.add_child(chess.Move.from_uci("e2e4"), "played")
    e5 = e4.add_child(chess.Move.from_uci("e7e5"), "played")
    # Alternatives at decision point
    e5.add_child(chess.Move.from_uci("g1f3"), "played", score_cp=30)
    e5.add_child(chess.Move.from_uci("d2d4"), "engine", score_cp=25)
    return GameTree(root=root, decision_point=e5, player_color=chess.WHITE)


# --- Helper tests ---

class TestHelpers:
    def test_describe_capture_non_capture(self):
        assert _describe_capture("Nf3") == "Nf3"

    def test_describe_capture_piece(self):
        result = _describe_capture("Bxf7+")
        assert "bishop captures on f7" in result
        assert "(Bxf7+)" in result

    def test_describe_capture_pawn(self):
        result = _describe_capture("dxc4")
        assert "pawn captures on c4" in result

    def test_format_pv_white_starts(self):
        result = _format_pv_with_numbers(["e5", "Nf3"], fullmove=1, white_starts=True)
        assert result == "1...e5 2.Nf3"

    def test_format_pv_black_starts(self):
        result = _format_pv_with_numbers(["d5", "c4"], fullmove=1, white_starts=False)
        assert result == "2.d5 c4"

    def test_format_pv_empty(self):
        assert _format_pv_with_numbers([], 1, True) == ""

    def test_format_numbered_move_white(self):
        assert _format_numbered_move("Bb5", 4, True) == "4. Bb5"

    def test_format_numbered_move_black(self):
        assert _format_numbered_move("c6", 4, False) == "4...c6"

    def test_game_pgn(self):
        tree = _tree_with_history()
        pgn = _game_pgn(tree)
        assert "1. e4" in pgn
        assert "e5" in pgn


# --- Piece diff tests ---

class TestPieceDiff:
    def test_no_change(self):
        before = MaterialCount(pawns=8, knights=2, bishops=2, rooks=2, queens=1)
        after = MaterialCount(pawns=8, knights=2, bishops=2, rooks=2, queens=1)
        diff = _piece_diff(before, after)
        assert all(v == 0 for v in diff.values())

    def test_lost_a_knight(self):
        before = MaterialCount(pawns=8, knights=2, bishops=2, rooks=2, queens=1)
        after = MaterialCount(pawns=8, knights=1, bishops=2, rooks=2, queens=1)
        diff = _piece_diff(before, after)
        assert diff["knights"] == -1


# --- _describe_result tests ---

class TestDescribeResult:
    def test_result_describes_pieces(self):
        """When material is exchanged, result should use piece names."""
        # Build a tree where white captures a knight
        board1 = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
        root = GameNode(board=chess.Board(), source="played")
        # e4
        e4 = root.add_child(chess.Move.from_uci("e2e4"), "played")
        # e5
        e5 = e4.add_child(chess.Move.from_uci("e7e5"), "played")
        # Nf3
        nf3 = e5.add_child(chess.Move.from_uci("g1f3"), "played")
        # Nc6
        nc6 = nf3.add_child(chess.Move.from_uci("b8c6"), "played")
        # Nxe5 (captures pawn)
        nxe5 = nc6.add_child(chess.Move.from_uci("f3e5"), "played")

        chain = [nxe5]
        result = _describe_result(chain, True)
        assert "Result:" in result

    def test_equal_material(self):
        """No captures → equal material."""
        root = GameNode(board=chess.Board(), source="played")
        e4 = root.add_child(chess.Move.from_uci("e2e4"), "played")
        chain = [e4]
        result = _describe_result(chain, True)
        assert "Equal material" in result


# --- serialize_report structure tests ---

class TestSerializeReport:
    def test_contains_student_color(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "Student is playing: White" in report

    def test_contains_student_move_section(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "# Student Move" in report

    def test_contains_move_on_own_line(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        lines = report.split("\n")
        assert any(line.strip() == "1. e4" for line in lines)

    def test_contains_quality(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "Move classification: mistake" in report

    def test_no_you_played(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "You played" not in report

    def test_contains_stronger_alternative(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "# Stronger Alternative" in report

    def test_good_move_uses_other_option(self):
        tree = _simple_tree()
        report = serialize_report(tree, "good", 0)
        assert "# Other option" in report
        assert "# Stronger Alternative" not in report

    def test_player_move_not_in_alternatives(self):
        """Player's move should not appear as an alternative."""
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        # e4 should not appear after "# Stronger Alternative"
        lines = report.split("\n")
        in_alt = False
        for line in lines:
            if "# Stronger Alternative" in line:
                in_alt = True
            if in_alt and line.strip() == "1. e4":
                pytest.fail("Player's move appeared as alternative")

    def test_rag_context_included(self):
        tree = _simple_tree()
        report = serialize_report(tree, "good", 0, rag_context="A fork attacks two pieces.")
        assert "Relevant chess knowledge" in report
        assert "fork attacks two pieces" in report

    def test_rag_context_omitted_when_empty(self):
        tree = _simple_tree()
        report = serialize_report(tree, "good", 0, rag_context="")
        assert "Relevant chess knowledge" not in report

    def test_no_game_section(self):
        """The # Game heading should not appear — PGN is in Position section."""
        tree = _tree_with_history()
        report = serialize_report(tree, "good", 0)
        assert "# Game" not in report

    def test_pgn_in_position_section(self):
        """PGN appears after # Position Before heading."""
        tree = _tree_with_history()
        report = serialize_report(tree, "good", 0)
        assert "1. e4" in report
        lines = report.split("\n")
        position_idx = next(i for i, l in enumerate(lines) if l.startswith("# Position Before"))
        # PGN should follow the Position heading
        post_position = "\n".join(lines[position_idx:position_idx + 5])
        assert "1. e4" in post_position

    def test_position_section_present(self):
        tree = _simple_tree()
        report = serialize_report(tree, "good", 0)
        assert "# Position Before White's Move" in report

    def test_prompt_length_reasonable(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert len(report) < 5000

    def test_sections_in_order(self):
        """Sections should appear in correct order."""
        tree = _tree_with_history()
        report = serialize_report(tree, "mistake", 60)
        lines = report.split("\n")
        section_indices = {}
        for i, line in enumerate(lines):
            if line.startswith("Student is playing"):
                section_indices["color"] = i
            elif line.startswith("# Position Before"):
                section_indices["position"] = i
            elif line == "# Student Move":
                section_indices["move"] = i
            elif line.startswith("# Stronger") or line.startswith("# Other") or line.startswith("# Also"):
                section_indices.setdefault("alt", i)

        assert section_indices.get("color", 0) < section_indices.get("position", 999)
        assert section_indices.get("position", 0) < section_indices.get("move", 999)
        if "alt" in section_indices:
            assert section_indices["move"] < section_indices["alt"]

    def test_position_has_observations(self):
        """Position section should have Observations category."""
        tree = _simple_tree()
        report = serialize_report(tree, "good", 0)
        assert "Observations:" in report


class TestSerializeReportMoveNumbers:
    def test_move_2_has_correct_number(self):
        tree = _tree_with_history()
        report = serialize_report(tree, "good", 0)
        assert "# Student Move" in report
        lines = report.split("\n")
        assert any(line.strip() == "2. Nf3" for line in lines)
