"""Tests for report.py — serialize_report section structure and content."""

import chess
import pytest

from server.analysis import MaterialCount, analyze_material
from server.game_tree import GameNode, GameTree
from server.report import (
    _describe_capture,
    _describe_result,
    _format_numbered_move,
    _format_pv_with_numbers,
    _game_pgn,
    _net_piece_diff,
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


def _tree_with_changes() -> GameTree:
    """Tree after 1.e4 e5 — both Nf3 (attacks e5) and Bc4 (pins f7) produce changes."""
    root = GameNode(board=chess.Board(), source="played")
    e4 = root.add_child(chess.Move.from_uci("e2e4"), "played")
    e5 = e4.add_child(chess.Move.from_uci("e7e5"), "played")
    e5.add_child(chess.Move.from_uci("g1f3"), "played", score_cp=30)
    e5.add_child(chess.Move.from_uci("f1c4"), "engine", score_cp=25)
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
        root = GameNode(board=chess.Board(), source="played")
        e4 = root.add_child(chess.Move.from_uci("e2e4"), "played")
        e5 = e4.add_child(chess.Move.from_uci("e7e5"), "played")
        nf3 = e5.add_child(chess.Move.from_uci("g1f3"), "played")
        nc6 = nf3.add_child(chess.Move.from_uci("b8c6"), "played")
        nxe5 = nc6.add_child(chess.Move.from_uci("f3e5"), "played")

        chain = [nxe5]
        result = _describe_result(chain, True)
        assert "Result:" in result

    def test_no_material_changes(self):
        """No captures — no material changes."""
        root = GameNode(board=chess.Board(), source="played")
        e4 = root.add_child(chess.Move.from_uci("e2e4"), "played")
        chain = [e4]
        result = _describe_result(chain, True)
        assert "No material changes" in result

    def test_queen_trade_plus_pawn(self):
        """Queen trade where student also wins a pawn — 'wins a pawn'."""
        # W(Q, R), B(Q, Pg7, Ph7). Qxf6 gxf6 Rxh7.
        # After: W(R), B(Pf6). Net: queens cancel, student wins a pawn.
        before = chess.Board("4k3/6pp/5q2/8/8/5Q2/8/4K2R w - - 0 1")
        root = GameNode(board=before, source="played")
        n1 = root.add_child(chess.Move.from_uci("f3f6"), "played")  # Qxf6
        n2 = n1.add_child(chess.Move.from_uci("g7f6"), "played")    # gxf6
        n3 = n2.add_child(chess.Move.from_uci("h1h7"), "played")    # Rxh7

        chain = [n1, n2, n3]
        result = _describe_result(chain, True)
        assert "wins a pawn" in result
        assert "queen" not in result.lower()

    def test_even_queen_trade(self):
        """Even queen trade — 'No material changes'."""
        before = chess.Board("4k3/6p1/5q2/8/8/5Q2/8/4K3 w - - 0 1")
        root = GameNode(board=before, source="played")
        n1 = root.add_child(chess.Move.from_uci("f3f6"), "played")  # Qxf6
        n2 = n1.add_child(chess.Move.from_uci("g7f6"), "played")    # gxf6
        chain = [n1, n2]
        result = _describe_result(chain, True)
        assert "No material changes" in result

    def test_rook_for_knight_trade(self):
        """Student trades rook for knight — 'trades a rook for a knight'."""
        before = chess.Board("4k3/3n4/8/3R4/8/8/8/4K3 w - - 0 1")
        root = GameNode(board=before, source="played")
        n1 = root.add_child(chess.Move.from_uci("d5d7"), "played")  # Rxd7
        n2 = n1.add_child(chess.Move.from_uci("e8d7"), "played")    # Kxd7
        chain = [n1, n2]
        result = _describe_result(chain, True)
        assert "trades" in result
        assert "rook" in result
        assert "knight" in result

    def test_simple_pawn_capture(self):
        """One-sided pawn capture still says 'wins a pawn'."""
        before = chess.Board("4k3/8/8/4p3/3P4/8/8/4K3 w - - 0 1")
        root = GameNode(board=before, source="played")
        n1 = root.add_child(chess.Move.from_uci("d4e5"), "played")  # dxe5
        chain = [n1]
        result = _describe_result(chain, True)
        assert "wins a pawn" in result


# --- serialize_report structure tests ---

class TestSerializeReport:
    def test_contains_student_color(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "The student played as: White" in report

    def test_contains_student_move_section(self):
        tree = _simple_tree()
        report = serialize_report(tree, "mistake", 60)
        assert "# Move Played" in report

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
        assert "# Position Before the Move" in report

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
            if line.startswith("The student played as"):
                section_indices["color"] = i
            elif line.startswith("# Position Before"):
                section_indices["position"] = i
            elif line == "# Move Played":
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

    def test_move_played_has_after_frame(self):
        tree = _tree_with_changes()
        report = serialize_report(tree, "mistake", 60)
        lines = report.split("\n")
        assert any(line.strip() == "After this move:" for line in lines)

    def test_alternative_has_creates_frame(self):
        tree = _tree_with_changes()
        report = serialize_report(tree, "mistake", 60)
        lines = report.split("\n")
        assert any(line.strip() == "This move creates:" for line in lines)


class TestSerializeReportMoveNumbers:
    def test_move_2_has_correct_number(self):
        tree = _tree_with_history()
        report = serialize_report(tree, "good", 0)
        assert "# Move Played" in report
        lines = report.split("\n")
        assert any(line.strip() == "2. Nf3" for line in lines)


# --- Bug #6 investigation: Bxf6 gxf6 material equality ---


class TestBug6MaterialResult:
    """Bug #6 claims 'Student wins a pawn' after an equal bishop-for-knight trade.

    The reported FEN has equal material (35-35). These tests verify that
    analyze_material and _describe_result agree it's equal.
    """

    def test_bxf6_gxf6_material_equal(self):
        """Post-trade FEN has 0 material imbalance."""
        # FEN from bug report: after Bxf6 gxf6 in a Ruy Lopez position
        # White: K, Q, 2R, B, N, 7P  Black: K, Q, 2R, B, N, 7P (approx)
        # Use a simplified position that matches the reported scenario:
        # White has B on g5, Black has N on f6, pawns on g7
        before_fen = "r1bqkb1r/ppp1pppp/2n2n2/3p2B1/3P4/2N2N2/PPP1PPPP/R2QKB1R w KQkq - 4 4"
        before = chess.Board(before_fen)

        # After Bxf6 gxf6: White loses bishop, Black loses knight + pawn g7 becomes f6
        before.push_uci("g5f6")  # Bxf6
        before.push_uci("g7f6")  # gxf6

        mat = analyze_material(before)
        # Both sides traded a minor piece (bishop for knight) — imbalance should be 0
        assert mat.imbalance == 0, (
            f"Expected 0 imbalance after Bxf6 gxf6 (bishop-for-knight trade), "
            f"got {mat.imbalance}"
        )

    def test_describe_result_equal_trade(self):
        """_describe_result for Bxf6 gxf6 reports no material win."""
        before_fen = "r1bqkb1r/ppp1pppp/2n2n2/3p2B1/3P4/2N2N2/PPP1PPPP/R2QKB1R w KQkq - 4 4"
        root_board = chess.Board(before_fen)
        root = GameNode(board=root_board, source="played")

        n1 = root.add_child(chess.Move.from_uci("g5f6"), "played")  # Bxf6
        n2 = n1.add_child(chess.Move.from_uci("g7f6"), "played")    # gxf6

        chain = [n1, n2]
        result = _describe_result(chain, student_is_white=True)
        # Should NOT say "wins a pawn" — the trade is equal
        assert "wins" not in result.lower(), (
            f"Equal bishop-for-knight trade should not say 'wins': {result}"
        )
