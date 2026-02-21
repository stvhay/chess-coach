"""Tests for the coaching assessment module."""

import chess
import pytest

from server.coach import (
    Arrow,
    CoachingResponse,
    Highlight,
    MoveQuality,
    assess_move,
)
from server.engine import Evaluation


# Helper to create eval objects
def _eval(cp: int | None = None, mate: int | None = None) -> Evaluation:
    return Evaluation(
        score_cp=cp,
        score_mate=mate,
        depth=20,
        best_move="e2e4",
        pv=["e2e4"],
    )


# ---------------------------------------------------------------------------
# Move quality classification
# ---------------------------------------------------------------------------


class TestMoveQuality:
    def test_blunder(self):
        """Move losing >200cp is a blunder."""
        board_before = chess.Board()
        board_after = chess.Board()
        board_after.push_uci("e2e4")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="e2e4",
            eval_before=_eval(cp=50),
            eval_after=_eval(cp=-200),
            best_move_uci="d2d4",
        )
        assert result is not None
        assert result.quality == MoveQuality.BLUNDER

    def test_mistake(self):
        """Move losing 100-200cp is a mistake."""
        board_before = chess.Board()
        board_after = chess.Board()
        board_after.push_uci("e2e4")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="e2e4",
            eval_before=_eval(cp=50),
            eval_after=_eval(cp=-80),
            best_move_uci="d2d4",
        )
        assert result is not None
        assert result.quality == MoveQuality.MISTAKE

    def test_inaccuracy(self):
        """Move losing 50-100cp is an inaccuracy."""
        board_before = chess.Board()
        board_after = chess.Board()
        board_after.push_uci("e2e4")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="e2e4",
            eval_before=_eval(cp=30),
            eval_after=_eval(cp=-40),
            best_move_uci="d2d4",
        )
        assert result is not None
        assert result.quality == MoveQuality.INACCURACY

    def test_good_move_returns_none(self):
        """Routine good move returns None (coach stays silent)."""
        board_before = chess.Board()
        board_after = chess.Board()
        board_after.push_uci("e2e4")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="e2e4",
            eval_before=_eval(cp=30),
            eval_after=_eval(cp=25),
            best_move_uci="e2e4",
        )
        assert result is None

    def test_best_move_in_sharp_position_is_brilliant(self):
        """Playing the only good move when alternatives lose big is brilliant."""
        board_before = chess.Board()
        board_after = chess.Board()
        board_after.push_uci("e2e4")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="e2e4",
            eval_before=_eval(cp=200),
            eval_after=_eval(cp=210),
            best_move_uci="e2e4",
            position_is_sharp=True,
        )
        assert result is not None
        assert result.quality == MoveQuality.BRILLIANT

    def test_missed_mate_is_blunder(self):
        """If eval_before had mate and eval_after doesn't, it's a blunder."""
        board_before = chess.Board()
        board_after = chess.Board()
        board_after.push_uci("e2e4")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="e2e4",
            eval_before=_eval(mate=3),
            eval_after=_eval(cp=100),
            best_move_uci="d2d4",
        )
        assert result is not None
        assert result.quality == MoveQuality.BLUNDER


class TestCoachingResponse:
    def test_blunder_has_message(self):
        board_before = chess.Board()
        board_after = chess.Board()
        board_after.push_uci("e2e4")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="e2e4",
            eval_before=_eval(cp=100),
            eval_after=_eval(cp=-200),
            best_move_uci="d2d4",
        )
        assert result is not None
        assert isinstance(result.message, str)
        assert len(result.message) > 0

    def test_blunder_has_arrows(self):
        """Blunder should show the best move as a green arrow."""
        board_before = chess.Board()
        board_after = chess.Board()
        board_after.push_uci("e2e4")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="e2e4",
            eval_before=_eval(cp=100),
            eval_after=_eval(cp=-200),
            best_move_uci="d2d4",
        )
        assert result is not None
        assert len(result.arrows) > 0
        best_arrow = [a for a in result.arrows if a.brush == "green"]
        assert len(best_arrow) > 0

    def test_response_serializable(self):
        """CoachingResponse should be convertible to dict."""
        from dataclasses import asdict
        board_before = chess.Board()
        board_after = chess.Board()
        board_after.push_uci("e2e4")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="e2e4",
            eval_before=_eval(cp=100),
            eval_after=_eval(cp=-200),
            best_move_uci="d2d4",
        )
        assert result is not None
        d = asdict(result)
        assert "quality" in d
        assert "message" in d
        assert "arrows" in d
        assert "highlights" in d


class TestTacticalCoaching:
    def test_hanging_piece_coaching(self):
        """When player leaves a piece hanging, coach should warn about it."""
        board_before = chess.Board("r1bqkb1r/pppppppp/2n2n2/4N3/2B5/8/PPPP1PPP/RNBQK2R b KQkq - 0 4")
        board_after = chess.Board("r1bqkb1r/pppppppp/2n2n2/4N3/2B5/8/PPPP1PPP/RNBQK2R b KQkq - 0 4")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="f3e5",
            eval_before=_eval(cp=50),
            eval_after=_eval(cp=-100),
            best_move_uci="d2d3",
        )
        assert result is not None
        assert result.quality in (MoveQuality.MISTAKE, MoveQuality.BLUNDER)

    def test_fork_detection_in_coaching(self):
        """When a fork exists after the move, coaching mentions it."""
        board_before = chess.Board("r3k3/8/8/2N5/8/8/8/4K3 w q - 0 1")
        board_after = chess.Board("r3k3/2N5/8/8/8/8/8/4K3 b q - 1 1")
        result = assess_move(
            board_before=board_before,
            board_after=board_after,
            player_move_uci="c5c7",
            eval_before=_eval(cp=300),
            eval_after=_eval(cp=500),
            best_move_uci="c5c7",
            position_is_sharp=True,
        )
        assert result is not None
        assert result.quality == MoveQuality.BRILLIANT
        assert len(result.arrows) >= 1
