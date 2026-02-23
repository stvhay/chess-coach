"""Tests for report.py — serialize_report section structure and content."""

import chess
import pytest

from server.game_tree import GameNode, GameTree
from server.report import (
    _describe_capture,
    _format_move_header,
    _format_pv_with_numbers,
    _game_pgn,
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

    def test_format_move_header_white(self):
        assert _format_move_header("Bb5", 4, True) == "# Move 4. Bb5"

    def test_format_move_header_black(self):
        assert _format_move_header("c6", 4, False) == "# Move 4...c6"

    def test_format_move_header_capture(self):
        result = _format_move_header("Nxe4", 3, True)
        assert "knight captures on e4 (Nxe4)" in result

    def test_game_pgn(self):
        tree = _tree_with_history()
        pgn = _game_pgn(tree)
        assert "1. e4" in pgn
        assert "e5" in pgn


# --- serialize_report structure tests ---

class TestSerializeReport:
    def test_contains_student_color(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "Student is playing: White" in report

    def test_contains_move_header(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "# Move 1. e4" in report

    def test_contains_quality(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "Move classification: mistake" in report

    def test_no_you_played(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "You played" not in report

    def test_contains_alternative(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "Stronger Alternative: d4" in report

    def test_good_move_uses_other_option(self):
        tree = _simple_tree()
        report = serialize_report(tree, "good", 0)
        assert "Other option: d4" in report
        assert "Stronger Alternative" not in report

    def test_player_move_not_in_alternatives(self):
        """Player's move should not appear as an alternative."""
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "Stronger Alternative: e4" not in report

    def test_rag_context_included(self):
        tree = _simple_tree()
        report = serialize_report(tree, "good", 0, rag_context="A fork attacks two pieces.")
        assert "Relevant chess knowledge" in report
        assert "fork attacks two pieces" in report

    def test_rag_context_omitted_when_empty(self):
        tree = _simple_tree()
        report = serialize_report(tree, "good", 0, rag_context="")
        assert "Relevant chess knowledge" not in report

    def test_game_pgn_included(self):
        tree = _tree_with_history()
        report = serialize_report(tree, "good", 0)
        assert "# Game" in report
        assert "1. e4" in report

    def test_position_section_present(self):
        tree = _simple_tree()
        report = serialize_report(tree, "good", 0)
        assert "# Position" in report

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
            elif line == "# Game":
                section_indices["game"] = i
            elif line == "# Position":
                section_indices["position"] = i
            elif line.startswith("# Move "):
                section_indices["move"] = i
            elif line.startswith("# Stronger") or line.startswith("# Other") or line.startswith("# Also"):
                section_indices.setdefault("alt", i)

        assert section_indices.get("color", 0) < section_indices.get("game", 999)
        assert section_indices.get("game", 0) < section_indices.get("position", 999)
        assert section_indices.get("position", 0) < section_indices.get("move", 999)
        if "alt" in section_indices:
            assert section_indices["move"] < section_indices["alt"]


class TestSerializeReportMoveNumbers:
    def test_move_2_has_correct_number(self):
        tree = _tree_with_history()
        report = serialize_report(tree, "good", 0)
        assert "# Move 2. Nf3" in report
