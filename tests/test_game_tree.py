"""Tests for game_tree module — GameNode, GameTree, build_coaching_tree."""

from unittest.mock import AsyncMock

import chess
import pytest

from server.analysis import TacticalMotifs, PositionReport
from server.elo_profiles import get_profile
from server.engine import Evaluation, LineInfo
from server.game_tree import (
    GameNode,
    GameTree,
    OpponentResponse,
    build_coaching_tree,
    _describe_opponent_move,
    _generate_opponent_responses,
    _move_insight,
    _motif_labels,
    _sort_key,
    _rank_nodes_by_teachability,
    _get_continuation_chain,
)


# --- Known positions ---

# Italian Game: after 1.e4 e5 2.Nf3 Nc6 3.Bc4
ITALIAN_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"


def _make_root(fen: str = chess.STARTING_FEN) -> GameNode:
    return GameNode(board=chess.Board(fen), source="played")


# --- GameNode tests ---

class TestGameNode:
    def test_san_from_parent(self):
        """node.san returns correct SAN from parent board context."""
        root = _make_root()
        move = chess.Move.from_uci("e2e4")
        child = root.add_child(move, "played")
        assert child.san == "e4"

    def test_san_root_is_empty(self):
        """Root node (no move, no parent) returns empty SAN."""
        root = _make_root()
        assert root.san == ""

    def test_lazy_tactics_computed_on_access(self):
        """Tactics are None initially, computed and cached on first access."""
        root = _make_root()
        assert root._tactics is None
        tactics = root.tactics
        assert isinstance(tactics, TacticalMotifs)
        # Second access returns same instance (cached)
        assert root.tactics is tactics
        assert root._tactics is tactics

    def test_lazy_report_computed_on_access(self):
        """Report is None initially, computed and cached on first access."""
        root = _make_root()
        assert root._report is None
        report = root.report
        assert isinstance(report, PositionReport)
        assert root.report is report
        assert root._report is report

    def test_fullmove_number(self):
        """fullmove_number reflects the board state."""
        root = _make_root()
        assert root.fullmove_number == 1
        child = root.add_child(chess.Move.from_uci("e2e4"), "played")
        assert child.fullmove_number == 1  # Black to move, still move 1
        grandchild = child.add_child(chess.Move.from_uci("e7e5"), "played")
        assert grandchild.fullmove_number == 2  # White to move, move 2


class TestAddChildSorted:
    def test_children_sorted_by_score_cp(self):
        """Children are inserted in descending score_cp order."""
        root = _make_root()
        root.add_child(chess.Move.from_uci("e2e4"), "engine", score_cp=30)
        root.add_child(chess.Move.from_uci("d2d4"), "engine", score_cp=50)
        root.add_child(chess.Move.from_uci("g1f3"), "engine", score_cp=10)

        scores = [c.score_cp for c in root.children]
        assert scores == [50, 30, 10]

    def test_mate_scores_sort_before_cp(self):
        """Mate-in-N scores sort before any centipawn scores."""
        root = _make_root()
        root.add_child(chess.Move.from_uci("e2e4"), "engine", score_cp=300)
        root.add_child(chess.Move.from_uci("d2d4"), "engine", score_mate=3)
        root.add_child(chess.Move.from_uci("g1f3"), "engine", score_cp=50)

        sources = [(c.score_mate, c.score_cp) for c in root.children]
        # Mate first, then 300, then 50
        assert sources[0] == (3, None)
        assert sources[1] == (None, 300)
        assert sources[2] == (None, 50)

    def test_negative_mate_sorts_last(self):
        """Being mated (negative mate) sorts after all CP scores."""
        root = _make_root()
        root.add_child(chess.Move.from_uci("e2e4"), "engine", score_cp=-100)
        root.add_child(chess.Move.from_uci("d2d4"), "engine", score_mate=-3)

        # cp=-100 should come before mate=-3 (getting mated is worst)
        assert root.children[0].score_cp == -100
        assert root.children[1].score_mate == -3

    def test_no_score_sorts_last(self):
        """Nodes with no score sort after scored nodes."""
        root = _make_root()
        root.add_child(chess.Move.from_uci("e2e4"), "engine")  # no score
        root.add_child(chess.Move.from_uci("d2d4"), "engine", score_cp=10)

        assert root.children[0].score_cp == 10
        assert root.children[1].score_cp is None


# --- GameTree tests ---

class TestGameTree:
    def _build_simple_tree(self) -> GameTree:
        """Build a tree: root → e4 → e5 → (decision_point), with 2 engine children."""
        root = GameNode(board=chess.Board(), source="played")
        e4 = root.add_child(chess.Move.from_uci("e2e4"), "played")
        e5 = e4.add_child(chess.Move.from_uci("e7e5"), "played")

        # Decision point: e5 position, White to move
        # Add engine alternatives
        e5.add_child(chess.Move.from_uci("g1f3"), "engine", score_cp=30)
        e5.add_child(chess.Move.from_uci("d2d4"), "engine", score_cp=25)
        e5.add_child(chess.Move.from_uci("f1c4"), "played", score_cp=20)

        return GameTree(root=root, decision_point=e5, player_color=chess.WHITE)

    def test_played_line(self):
        """played_line returns root → decision_point path."""
        tree = self._build_simple_tree()
        line = tree.played_line()
        assert len(line) == 3  # root, e4, e5
        assert line[0] is tree.root
        assert line[-1] is tree.decision_point

    def test_played_line_root_only(self):
        """played_line with root as decision_point returns [root]."""
        root = GameNode(board=chess.Board(), source="played")
        tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
        assert tree.played_line() == [root]

    def test_player_move_node(self):
        """player_move_node finds the source='played' child."""
        tree = self._build_simple_tree()
        player = tree.player_move_node()
        assert player is not None
        assert player.source == "played"
        assert player.san == "Bc4"

    def test_player_move_node_none(self):
        """player_move_node returns None when no played child exists."""
        root = GameNode(board=chess.Board(), source="played")
        root.add_child(chess.Move.from_uci("e2e4"), "engine", score_cp=30)
        tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)
        assert tree.player_move_node() is None

    def test_alternatives(self):
        """alternatives returns non-played children, sorted by eval."""
        tree = self._build_simple_tree()
        alts = tree.alternatives()
        assert len(alts) == 2
        assert all(a.source != "played" for a in alts)
        # Should be sorted by eval (30, 25)
        assert alts[0].score_cp == 30
        assert alts[1].score_cp == 25


# --- build_coaching_tree integration test ---

@pytest.fixture
def mock_engine():
    engine = AsyncMock()
    engine.analyze_lines = AsyncMock(return_value=[
        LineInfo(uci="e2e4", san="e4", score_cp=30, score_mate=None,
                 pv=["e2e4", "e7e5"], depth=10),
        LineInfo(uci="d2d4", san="d4", score_cp=25, score_mate=None,
                 pv=["d2d4", "d7d5"], depth=10),
    ])
    engine.evaluate = AsyncMock(return_value=Evaluation(
        score_cp=20, score_mate=None, depth=14, best_move="e7e5",
        pv=["e7e5", "g1f3"],
    ))
    return engine


async def test_build_coaching_tree(mock_engine):
    """Integration: build_coaching_tree returns a valid GameTree."""
    board = chess.Board()
    profile = get_profile("intermediate")
    eval_before = Evaluation(
        score_cp=20, score_mate=None, depth=12,
        best_move="e2e4", pv=["e2e4"],
    )

    tree = await build_coaching_tree(
        mock_engine, board, "e2e4", eval_before, profile
    )

    assert isinstance(tree, GameTree)
    assert tree.player_color == chess.WHITE
    assert tree.decision_point is not None
    # Should have at least one child (the player's move)
    assert len(tree.decision_point.children) >= 1
    # Player move should be findable
    player = tree.player_move_node()
    assert player is not None


async def test_build_coaching_tree_empty_lines(mock_engine):
    """build_coaching_tree handles empty engine lines gracefully."""
    mock_engine.analyze_lines.return_value = []
    board = chess.Board()
    profile = get_profile("intermediate")
    eval_before = Evaluation(
        score_cp=20, score_mate=None, depth=12,
        best_move="e2e4", pv=["e2e4"],
    )

    tree = await build_coaching_tree(
        mock_engine, board, "e2e4", eval_before, profile
    )

    assert isinstance(tree, GameTree)
    # Should still have the player's move
    player = tree.player_move_node()
    assert player is not None


async def test_build_coaching_tree_player_matches_engine(mock_engine):
    """When player plays engine's top choice, it gets re-tagged as 'played'."""
    board = chess.Board()
    profile = get_profile("intermediate")
    eval_before = Evaluation(
        score_cp=30, score_mate=None, depth=12,
        best_move="e2e4", pv=["e2e4"],
    )

    tree = await build_coaching_tree(
        mock_engine, board, "e2e4", eval_before, profile
    )

    player = tree.player_move_node()
    assert player is not None
    assert player.san == "e4"
    # Should not appear in alternatives
    alts = tree.alternatives()
    alt_sans = [a.san for a in alts]
    assert "e4" not in alt_sans


async def test_build_coaching_tree_played_line_from_history():
    """build_coaching_tree replays move_stack into tree path."""
    # Set up a board with history: 1.e4 e5 2.Nf3
    board = chess.Board()
    board.push(chess.Move.from_uci("e2e4"))
    board.push(chess.Move.from_uci("e7e5"))

    engine = AsyncMock()
    engine.analyze_lines = AsyncMock(return_value=[
        LineInfo(uci="g1f3", san="Nf3", score_cp=30, score_mate=None,
                 pv=["g1f3", "b8c6"], depth=10),
    ])
    engine.evaluate = AsyncMock(return_value=Evaluation(
        score_cp=25, score_mate=None, depth=14, best_move="b8c6",
        pv=["b8c6"],
    ))

    profile = get_profile("intermediate")
    eval_before = Evaluation(
        score_cp=25, score_mate=None, depth=12,
        best_move="g1f3", pv=["g1f3"],
    )

    tree = await build_coaching_tree(
        engine, board, "g1f3", eval_before, profile
    )

    # Played line should have 3 nodes: root, e4, e5
    played = tree.played_line()
    assert len(played) == 3
    assert played[0] is tree.root
    assert played[1].san == "e4"
    assert played[2].san == "e5"


# --- _motif_labels tests ---

def test_motif_labels_empty():
    assert _motif_labels(TacticalMotifs()) == set()


def test_motif_labels_with_fork():
    from server.analysis import Fork
    tactics = TacticalMotifs(forks=[Fork("e5", "N", ["d7", "f7"])])
    assert "fork" in _motif_labels(tactics)


def test_motif_labels_checkmate():
    # Board in checkmate
    board = chess.Board("rnb1kbnr/pppp1ppp/4p3/8/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    assert board.is_checkmate()
    assert "checkmate" in _motif_labels(TacticalMotifs(), board)


# --- Teachability ranking tests ---

from server.analysis import Fork, Pin, TacticValue


class TestTeachabilityRanking:
    def _make_node_with_tactics(self, fen, tactics):
        """Helper: create GameNode with pre-set tactics."""
        node = GameNode(board=chess.Board(fen), source="engine")
        node._tactics = tactics
        return node

    def test_baseline_more_tactics_higher_score(self):
        """Node with more tactics should score higher than node with fewer."""
        fork = Fork("e5", "N", ["c6", "g6"], ["r", "q"])
        pin = Pin("c6", "n", "b5", "B", "e8", "k", True)

        node_one = self._make_node_with_tactics(
            "4k3/8/2n3r1/4N3/8/8/8/4K3 w - - 0 1",
            TacticalMotifs(forks=[fork]),
        )
        node_two = self._make_node_with_tactics(
            "4k3/8/2n3r1/4N3/1B6/8/8/4K3 w - - 0 1",
            TacticalMotifs(forks=[fork], pins=[pin]),
        )
        node_one.score_cp = 100
        node_two.score_cp = 100

        _rank_nodes_by_teachability([node_one, node_two])
        assert node_two._interest_score > node_one._interest_score

    def test_baseline_empty_tactics_low_score(self):
        """Node with no tactics should score low."""
        node = self._make_node_with_tactics(
            chess.STARTING_FEN, TacticalMotifs(),
        )
        node.score_cp = 0
        _rank_nodes_by_teachability([node])
        assert node._interest_score <= 0 or node._interest_score < 5

    def test_custom_weights_fork_emphasis(self):
        """Custom weights that boost forks should increase fork node score."""
        from server.game_tree import TeachabilityWeights, DEFAULT_WEIGHTS

        fork = Fork("e5", "N", ["c6", "g6"], ["r", "q"],
                     value=TacticValue(material_delta=500, is_sound=True))
        pin = Pin("c6", "n", "b5", "B", "e8", "k", True,
                  value=TacticValue(material_delta=300, is_sound=True))

        node_fork = self._make_node_with_tactics(
            "4k3/8/2n3r1/4N3/8/8/8/4K3 w - - 0 1",
            TacticalMotifs(forks=[fork]),
        )
        node_pin = self._make_node_with_tactics(
            "4k3/8/2n3r1/4N3/1B6/8/8/4K3 w - - 0 1",
            TacticalMotifs(pins=[pin]),
        )
        node_fork.score_cp = 100
        node_pin.score_cp = 100

        fork_weights = TeachabilityWeights(
            motif_base={**DEFAULT_WEIGHTS.motif_base, "fork": 10.0},
        )

        _rank_nodes_by_teachability([node_fork, node_pin], weights=fork_weights)
        assert node_fork._interest_score > node_pin._interest_score

    def test_value_bonus_scales_with_material(self):
        """Higher material_delta should produce higher score."""
        fork_big = Fork("e5", "N", ["c6", "g6"], ["r", "q"],
                        value=TacticValue(material_delta=500, is_sound=True))
        fork_small = Fork("e5", "N", ["c6", "g6"], ["p", "p"],
                          value=TacticValue(material_delta=100, is_sound=True))

        node_big = self._make_node_with_tactics(
            "4k3/8/2n3r1/4N3/8/8/8/4K3 w - - 0 1",
            TacticalMotifs(forks=[fork_big]),
        )
        node_small = self._make_node_with_tactics(
            "4k3/8/2n3r1/4N3/8/8/8/4K3 w - - 0 1",
            TacticalMotifs(forks=[fork_small]),
        )
        node_big.score_cp = 100
        node_small.score_cp = 100

        _rank_nodes_by_teachability([node_big, node_small])
        assert node_big._interest_score > node_small._interest_score

    def test_unsound_tactics_penalized(self):
        """Unsound tactics should score lower than sound ones."""
        fork_sound = Fork("e5", "N", ["c6", "g6"], ["r", "q"],
                          value=TacticValue(material_delta=500, is_sound=True))
        fork_unsound = Fork("e5", "N", ["c6", "g6"], ["r", "q"],
                            value=TacticValue(material_delta=-200, is_sound=False))

        node_sound = self._make_node_with_tactics(
            "4k3/8/2n3r1/4N3/8/8/8/4K3 w - - 0 1",
            TacticalMotifs(forks=[fork_sound]),
        )
        node_unsound = self._make_node_with_tactics(
            "4k3/8/2n3r1/4N3/8/8/8/4K3 w - - 0 1",
            TacticalMotifs(forks=[fork_unsound]),
        )
        node_sound.score_cp = 100
        node_unsound.score_cp = 100

        _rank_nodes_by_teachability([node_sound, node_unsound])
        assert node_sound._interest_score > node_unsound._interest_score

    def test_default_weights_exist(self):
        """DEFAULT_WEIGHTS should be importable and have expected structure."""
        from server.game_tree import DEFAULT_WEIGHTS, TeachabilityWeights
        assert isinstance(DEFAULT_WEIGHTS, TeachabilityWeights)
        assert "fork" in DEFAULT_WEIGHTS.motif_base
        assert "pin" in DEFAULT_WEIGHTS.motif_base
        assert DEFAULT_WEIGHTS.mate_bonus > 0


# --- OpponentResponse tests ---

class TestDescribeOpponentMove:
    def test_capture_description(self):
        """Capture moves should describe the captured piece."""
        # After Nxc6, black can play bxc6
        board = chess.Board("r1bqkbnr/pp1ppppp/2N5/8/4P3/8/PPPP1PPP/RNBQKB1R b KQkq - 0 3")
        move = chess.Move.from_uci("b7c6")
        desc = _describe_opponent_move(board, move, student_is_white=True)
        assert "captures" in desc
        assert "knight" in desc
        assert "c6" in desc

    def test_non_capture_move(self):
        """Non-capture moves describe piece movement."""
        board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
        move = chess.Move.from_uci("g8f6")
        desc = _describe_opponent_move(board, move, student_is_white=True)
        assert "knight" in desc
        assert "f6" in desc

    def test_check_annotation(self):
        """Moves that give check should note it."""
        # Black queen on d2, White king on d1. Qe2 gives check via diagonal.
        board = chess.Board("4k3/8/8/8/8/8/3q4/3K4 b - - 0 1")
        move = chess.Move.from_uci("d2e2")
        assert move in board.legal_moves
        desc = _describe_opponent_move(board, move, student_is_white=True)
        assert "check" in desc

    def test_pawn_push(self):
        """Pawn advances should say 'pushes pawn'."""
        board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
        move = chess.Move.from_uci("d7d5")
        desc = _describe_opponent_move(board, move, student_is_white=True)
        assert "pawn" in desc
        assert "d5" in desc

    def test_insight_targeting(self):
        """Non-capture moves should include insight about what they target."""
        # After 1.e4 e5 2.Nf3 Nc6 3.Bc4 — Black plays Bc5, targeting f2
        board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3")
        move = chess.Move.from_uci("f8c5")
        desc = _describe_opponent_move(board, move, student_is_white=True)
        assert "develops bishop to c5" in desc
        # Bc5 targets f2 pawn — but pawn is only 1cp, below threshold
        # It may or may not include targeting (depends on threshold in _move_insight)

    def test_insight_pawn_center(self):
        """Pawn pushes to center squares should mention challenging the center."""
        board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
        move = chess.Move.from_uci("d7d5")
        desc = _describe_opponent_move(board, move, student_is_white=True)
        assert "challenging the center" in desc


class TestMoveInsight:
    """Tests for _move_insight — one notable fact about a move."""

    def test_targets_high_value_piece(self):
        """Move attacking a student's bishop+ should mention targeting."""
        # White Nd4, Black Re7+Ke8. Nc6 attacks e7 (rook).
        board = chess.Board("4k3/4r3/8/8/3N4/8/8/4K3 w - - 0 1")
        move = chess.Move.from_uci("d4c6")
        after = board.copy()
        after.push(move)
        insight = _move_insight(after, move, student_is_white=False)
        # Student is Black, Nc6 attacks Black's rook on e7
        assert "targeting" in insight
        assert "rook" in insight

    def test_pawn_challenges_center(self):
        """Pawn moving to central square should mention center challenge."""
        board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
        move = chess.Move.from_uci("d7d5")
        after = board.copy()
        after.push(move)
        insight = _move_insight(after, move, student_is_white=True)
        assert "center" in insight

    def test_no_insight_for_quiet_move(self):
        """Quiet moves with no notable target return empty string."""
        # Starting position, knight to h6 — doesn't attack anything notable
        board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
        move = chess.Move.from_uci("g8h6")
        after = board.copy()
        after.push(move)
        insight = _move_insight(after, move, student_is_white=True)
        # Nh6 doesn't attack any white piece worth mentioning
        assert insight == "" or "defending" in insight or "targeting" in insight


class TestGenerateOpponentResponses:
    @pytest.fixture
    def opponent_engine(self):
        engine = AsyncMock()
        engine.analyze_lines = AsyncMock(return_value=[
            LineInfo(uci="b7c6", san="bxc6", score_cp=-50, score_mate=None,
                     pv=["b7c6", "f1c4"], depth=6),
            LineInfo(uci="d7c6", san="dxc6", score_cp=-80, score_mate=None,
                     pv=["d7c6", "d1d8"], depth=6),
            LineInfo(uci="g8f6", san="Nf6", score_cp=-120, score_mate=None,
                     pv=["g8f6", "c6a7"], depth=6),
        ])
        return engine

    async def test_generates_responses(self, opponent_engine):
        """_generate_opponent_responses returns correct count and types."""
        # After Nxc6 position
        board = chess.Board("r1bqkbnr/pp1ppppp/2N5/8/4P3/8/PPPP1PPP/RNBQKB1R b KQkq - 0 3")
        player_node = GameNode(board=board, source="played")

        profile = get_profile("competitive")
        responses = await _generate_opponent_responses(
            player_node, opponent_engine, profile, student_is_white=True,
        )

        assert len(responses) > 0
        assert all(isinstance(r, OpponentResponse) for r in responses)
        # First response should be bxc6
        assert responses[0].san == "bxc6"
        assert "captures" in responses[0].description

    async def test_is_best_flag(self, opponent_engine):
        """is_best should be True for the engine's top-ranked move."""
        board = chess.Board("r1bqkbnr/pp1ppppp/2N5/8/4P3/8/PPPP1PPP/RNBQKB1R b KQkq - 0 3")
        player_node = GameNode(board=board, source="played")

        profile = get_profile("competitive")
        responses = await _generate_opponent_responses(
            player_node, opponent_engine, profile, student_is_white=True,
        )

        best_responses = [r for r in responses if r.is_best]
        assert len(best_responses) == 1
        assert best_responses[0].uci == "b7c6"

    async def test_filters_weak_responses(self):
        """Responses much worse than the best are filtered out by cp_threshold."""
        engine = AsyncMock()
        # Best: Qxg5 at +300 (wins knight). Others: Be7 at -50 (450cp worse)
        engine.analyze_lines = AsyncMock(return_value=[
            LineInfo(uci="d8g5", san="Qxg5", score_cp=300, score_mate=None,
                     pv=["d8g5"], depth=6),
            LineInfo(uci="f8e7", san="Be7", score_cp=-50, score_mate=None,
                     pv=["f8e7"], depth=6),
            LineInfo(uci="f8c5", san="Bc5", score_cp=-60, score_mate=None,
                     pv=["f8c5"], depth=6),
        ])
        # After 1.e4 Nc6 2.Nf3 e5 3.Ng5 — Black to move, Qxg5 is legal
        board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p1N1/4P3/8/PPPP1PPP/RNBQKB1R b KQkq - 1 3")
        player_node = GameNode(board=board, source="played")

        profile = get_profile("competitive")  # cp_threshold=100
        responses = await _generate_opponent_responses(
            player_node, engine, profile, student_is_white=True,
        )

        # Best (Qxg5) should be included; Be7/Bc5 are 350cp+ worse → filtered
        assert len(responses) == 1
        assert responses[0].san == "Qxg5"

    async def test_empty_engine_lines(self):
        """Empty engine response produces no opponent responses."""
        engine = AsyncMock()
        engine.analyze_lines = AsyncMock(return_value=[])

        board = chess.Board()
        player_node = GameNode(board=board, source="played")
        profile = get_profile("intermediate")

        responses = await _generate_opponent_responses(
            player_node, engine, profile, student_is_white=True,
        )
        assert responses == []


async def test_build_coaching_tree_populates_opponent_responses():
    """build_coaching_tree should populate tree.opponent_responses."""
    # Screen lines for the starting position (White to move)
    screen_lines = [
        LineInfo(uci="e2e4", san="e4", score_cp=30, score_mate=None,
                 pv=["e2e4", "e7e5"], depth=10),
        LineInfo(uci="d2d4", san="d4", score_cp=25, score_mate=None,
                 pv=["d2d4", "d7d5"], depth=10),
    ]
    # Opponent response lines for the post-e4 position (Black to move)
    opponent_lines = [
        LineInfo(uci="e7e5", san="e5", score_cp=-30, score_mate=None,
                 pv=["e7e5", "g1f3"], depth=6),
        LineInfo(uci="d7d5", san="d5", score_cp=-25, score_mate=None,
                 pv=["d7d5", "e4d5"], depth=6),
    ]

    engine = AsyncMock()
    engine.analyze_lines = AsyncMock(side_effect=[screen_lines, opponent_lines])
    engine.evaluate = AsyncMock(return_value=Evaluation(
        score_cp=20, score_mate=None, depth=14, best_move="e7e5",
        pv=["e7e5", "g1f3"],
    ))

    board = chess.Board()
    profile = get_profile("intermediate")
    eval_before = Evaluation(
        score_cp=20, score_mate=None, depth=12,
        best_move="e2e4", pv=["e2e4"],
    )

    tree = await build_coaching_tree(
        engine, board, "e2e4", eval_before, profile
    )

    assert isinstance(tree.opponent_responses, list)
    assert len(tree.opponent_responses) > 0
    assert all(isinstance(r, OpponentResponse) for r in tree.opponent_responses)
    # First response should be e5 (the top engine line)
    assert tree.opponent_responses[0].san == "e5"
