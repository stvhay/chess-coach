"""Tests for screener-equivalent functionality now in game_tree.py.

rank_by_teachability has been moved into game_tree._rank_nodes_by_teachability.
screen_and_validate has been replaced by build_coaching_tree.
These tests validate the same behaviors through the new interfaces.
"""

from unittest.mock import AsyncMock

import chess
import pytest

from server.analysis import TacticalMotifs, Fork
from server.elo_profiles import get_profile
from server.engine import Evaluation, LineInfo
from server.game_tree import (
    GameNode,
    GameTree,
    build_coaching_tree,
    _rank_nodes_by_teachability,
    _motif_labels,
)


# --- Helper to build test nodes ---

def _make_node(
    parent: GameNode | None = None,
    score_cp: int = 50,
    tactics: TacticalMotifs | None = None,
) -> GameNode:
    """Create a GameNode for testing, optionally with pre-set tactics."""
    board = chess.Board() if parent is None else parent.board.copy()
    node = GameNode(
        board=board,
        source="engine",
        score_cp=score_cp,
    )
    if tactics is not None:
        node._tactics = tactics
    else:
        node._tactics = TacticalMotifs()
    node.parent = parent
    return node


def _make_child_with_motifs(
    parent: GameNode,
    move_uci: str,
    score_cp: int = 50,
    tactics: TacticalMotifs | None = None,
) -> GameNode:
    """Add a child to parent with specific tactics (pre-cached)."""
    move = chess.Move.from_uci(move_uci)
    child = parent.add_child(move, "engine", score_cp=score_cp)
    if tactics is not None:
        child._tactics = tactics
    else:
        child._tactics = TacticalMotifs()
    return child


# --- rank_by_teachability tests (adapted from old screener tests) ---

def test_rank_empty_list():
    _rank_nodes_by_teachability([])
    # No crash


def test_rank_single_node():
    root = GameNode(board=chess.Board(), source="played")
    root._tactics = TacticalMotifs()
    node = _make_child_with_motifs(root, "e2e4", score_cp=50)
    _rank_nodes_by_teachability([node])
    assert hasattr(node, '_interest_score')


def test_rank_favors_early_tactics():
    """Node with a fork in continuation should score higher than one without."""
    root = GameNode(board=chess.Board(), source="played")
    root._tactics = TacticalMotifs()

    # Node with fork in child (early tactic)
    node_with = _make_child_with_motifs(root, "e2e4", score_cp=50)
    fork_tactics = TacticalMotifs(forks=[Fork("e5", "N", ["d7", "f7"])])
    # Add a child with fork tactics
    child_board = node_with.board.copy()
    child_board.push(chess.Move.from_uci("e7e5"))
    fork_child = GameNode(board=child_board, source="engine", parent=node_with)
    fork_child._tactics = fork_tactics
    node_with.children.append(fork_child)

    # Node without tactics
    node_without = _make_child_with_motifs(root, "d2d4", score_cp=50)

    _rank_nodes_by_teachability([node_without, node_with])
    assert node_with._interest_score > node_without._interest_score


def test_rank_penalizes_large_eval_loss():
    root = GameNode(board=chess.Board(), source="played")
    root._tactics = TacticalMotifs()

    best = _make_child_with_motifs(root, "e2e4", score_cp=200)
    bad = _make_child_with_motifs(root, "d2d4", score_cp=0)

    _rank_nodes_by_teachability([best, bad])
    assert bad._interest_score < best._interest_score


# --- build_coaching_tree integration tests (mocked engine) ---

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


async def test_build_coaching_tree_returns_tree(mock_engine):
    board = chess.Board()
    profile = get_profile("intermediate")
    eval_before = Evaluation(score_cp=20, score_mate=None, depth=12,
                             best_move="e2e4", pv=["e2e4"])

    tree = await build_coaching_tree(
        mock_engine, board, "e2e4", eval_before, profile
    )

    assert isinstance(tree, GameTree)
    assert tree.player_move_node() is not None
    assert tree.player_move_node().san == "e4"
    assert len(tree.decision_point.children) > 0


async def test_build_coaching_tree_empty_lines(mock_engine):
    mock_engine.analyze_lines.return_value = []
    board = chess.Board()
    profile = get_profile("intermediate")
    eval_before = Evaluation(score_cp=20, score_mate=None, depth=12,
                             best_move="e2e4", pv=["e2e4"])

    tree = await build_coaching_tree(
        mock_engine, board, "e2e4", eval_before, profile
    )

    assert isinstance(tree, GameTree)


async def test_build_coaching_tree_uses_profile_depths(mock_engine):
    board = chess.Board()
    profile = get_profile("competitive")
    eval_before = Evaluation(score_cp=20, score_mate=None, depth=12,
                             best_move="e2e4", pv=["e2e4"])

    await build_coaching_tree(
        mock_engine, board, "e2e4", eval_before, profile
    )

    mock_engine.analyze_lines.assert_called_once_with(
        board.fen(), n=profile.screen_breadth, depth=profile.screen_depth
    )
