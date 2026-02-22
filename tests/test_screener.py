from unittest.mock import AsyncMock, patch

import chess
import pytest

from server.annotator import AnnotatedLine, PlyAnnotation
from server.analysis import TacticalMotifs, Fork
from server.elo_profiles import get_profile
from server.engine import Evaluation, LineInfo
from server.screener import (
    CoachingContext,
    rank_by_teachability,
    screen_and_validate,
)


# --- rank_by_teachability tests ---

def _make_annotation(ply: int, new_motifs: list[str] | None = None,
                     material_change: int = 0, summary: str = "") -> PlyAnnotation:
    return PlyAnnotation(
        ply=ply,
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        move_san="e4",
        tactics=TacticalMotifs(),
        material_change=material_change,
        new_motifs=new_motifs or [],
        position_summary=summary,
    )


def _make_line(score_cp: int, annotations: list[PlyAnnotation] | None = None) -> AnnotatedLine:
    return AnnotatedLine(
        first_move_san="e4",
        first_move_uci="e2e4",
        score_cp=score_cp,
        score_mate=None,
        pv_san=["e4"],
        annotations=annotations or [],
    )


def test_rank_empty_list():
    result = rank_by_teachability([])
    assert result == []


def test_rank_single_line():
    line = _make_line(50, [_make_annotation(0)])
    result = rank_by_teachability([line])
    assert len(result) == 1


def test_rank_favors_early_tactics():
    # Line with a fork at ply 1 should score higher than line with no tactics
    fork_ann = _make_annotation(1, new_motifs=["fork"])
    line_with_tactics = _make_line(50, [_make_annotation(0), fork_ann])
    line_without = _make_line(50, [_make_annotation(0), _make_annotation(1)])

    result = rank_by_teachability([line_without, line_with_tactics])
    assert result[0].interest_score > result[1].interest_score


def test_rank_penalizes_deep_only_tactics():
    # Motifs only at ply 5+ should get penalized
    deep_ann = _make_annotation(5, new_motifs=["fork"])
    line_deep = _make_line(50, [_make_annotation(i) for i in range(5)] + [deep_ann])
    line_none = _make_line(50, [_make_annotation(i) for i in range(6)])

    result = rank_by_teachability([line_deep, line_none], max_concept_depth=4)
    # deep-only tactics get -2 penalty
    assert line_deep.interest_score < line_none.interest_score


def test_rank_penalizes_large_eval_loss():
    best_line = _make_line(200, [_make_annotation(0)])
    bad_line = _make_line(0, [_make_annotation(0)])  # 200cp worse than best

    rank_by_teachability([best_line, bad_line])
    assert bad_line.interest_score < best_line.interest_score


def test_rank_rewards_material_gain():
    capture_ann = _make_annotation(0, material_change=100)
    line_capture = _make_line(50, [capture_ann])
    line_quiet = _make_line(50, [_make_annotation(0)])

    rank_by_teachability([line_capture, line_quiet])
    assert line_capture.interest_score > line_quiet.interest_score


def test_rank_rewards_positional_themes():
    pos_ann = _make_annotation(0, summary="White has passed pawns on d5.")
    line_positional = _make_line(50, [pos_ann])
    line_plain = _make_line(50, [_make_annotation(0, summary="Position is balanced.")])

    rank_by_teachability([line_positional, line_plain])
    assert line_positional.interest_score > line_plain.interest_score


# --- screen_and_validate integration tests (mocked engine) ---

@pytest.fixture
def mock_engine():
    engine = AsyncMock()
    engine.analyze_lines = AsyncMock(return_value=[
        LineInfo(uci="e2e4", san="e4", score_cp=30, score_mate=None, pv=["e2e4", "e7e5"], depth=10),
        LineInfo(uci="d2d4", san="d4", score_cp=25, score_mate=None, pv=["d2d4", "d7d5"], depth=10),
    ])
    engine.evaluate = AsyncMock(return_value=Evaluation(
        score_cp=20, score_mate=None, depth=14, best_move="e7e5", pv=["e7e5", "g1f3"],
    ))
    return engine


async def test_screen_and_validate_returns_context(mock_engine):
    board = chess.Board()
    profile = get_profile("intermediate")
    eval_before = Evaluation(score_cp=20, score_mate=None, depth=12, best_move="e2e4", pv=["e2e4"])

    ctx = await screen_and_validate(
        mock_engine, board, "e2e4", eval_before, profile
    )

    assert isinstance(ctx, CoachingContext)
    assert ctx.player_move is not None
    assert ctx.player_move.first_move_uci == "e2e4"
    assert len(ctx.best_lines) > 0


async def test_screen_and_validate_empty_lines(mock_engine):
    mock_engine.analyze_lines.return_value = []
    board = chess.Board()
    profile = get_profile("intermediate")
    eval_before = Evaluation(score_cp=20, score_mate=None, depth=12, best_move="e2e4", pv=["e2e4"])

    ctx = await screen_and_validate(
        mock_engine, board, "e2e4", eval_before, profile
    )

    assert isinstance(ctx, CoachingContext)
    assert ctx.best_lines == []


async def test_screen_and_validate_uses_profile_depths(mock_engine):
    board = chess.Board()
    profile = get_profile("competitive")
    eval_before = Evaluation(score_cp=20, score_mate=None, depth=12, best_move="e2e4", pv=["e2e4"])

    await screen_and_validate(
        mock_engine, board, "e2e4", eval_before, profile
    )

    # Check that analyze_lines was called with the profile's screen params
    mock_engine.analyze_lines.assert_called_once_with(
        board.fen(), n=profile.screen_breadth, depth=profile.screen_depth
    )
