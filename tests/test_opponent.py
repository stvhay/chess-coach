"""Tests for the opponent move selection module."""

from unittest.mock import AsyncMock

import chess
import pytest

from server.engine import MoveInfo
from server.opponent import (
    GamePhase,
    detect_game_phase,
    filter_candidates,
    select_opponent_move,
)


# ---------------------------------------------------------------------------
# TestGamePhaseDetection
# ---------------------------------------------------------------------------


class TestGamePhaseDetection:
    def test_starting_position_is_opening(self):
        board = chess.Board()
        assert detect_game_phase(board) == GamePhase.OPENING

    def test_developed_position_is_middlegame(self):
        # Both sides fully developed (all 4 minors moved), move 10
        board = chess.Board(
            "r2q1rk1/ppp1bppp/2np1n2/4p3/2B1P1b1/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 10"
        )
        assert detect_game_phase(board) == GamePhase.MIDDLEGAME

    def test_queenless_position_is_endgame(self):
        # No queens on the board
        board = chess.Board(
            "r3kb1r/ppp2ppp/2n2n2/3pp3/3PP3/2N2N2/PPP2PPP/R3KB1R w KQkq - 0 8"
        )
        assert detect_game_phase(board) == GamePhase.ENDGAME

    def test_low_material_is_endgame(self):
        # Rook + pawns endgame (each side <= 13 points)
        board = chess.Board("4k3/5ppp/8/8/8/8/5PPP/4K2R w K - 0 30")
        assert detect_game_phase(board) == GamePhase.ENDGAME

    def test_early_move_undeveloped_is_opening(self):
        # Move 3, barely any development
        board = chess.Board(
            "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
        )
        assert detect_game_phase(board) == GamePhase.OPENING

    def test_late_game_with_queens_and_material_is_middlegame(self):
        # Move 20 but still queens and lots of material
        board = chess.Board(
            "r1bq1rk1/ppp2ppp/2n2n2/3pp3/2BPP3/5N2/PPP2PPP/RNBQ1RK1 w - - 0 20"
        )
        assert detect_game_phase(board) == GamePhase.MIDDLEGAME


# ---------------------------------------------------------------------------
# TestCandidateFiltering
# ---------------------------------------------------------------------------


class TestCandidateFiltering:
    def test_single_candidate_passes(self):
        candidates = [MoveInfo(uci="e2e4", score_cp=50, score_mate=None)]
        result = filter_candidates(candidates, GamePhase.OPENING)
        assert len(result) == 1
        assert result[0].uci == "e2e4"

    def test_filters_by_threshold_opening(self):
        candidates = [
            MoveInfo(uci="e2e4", score_cp=50, score_mate=None),
            MoveInfo(uci="d2d4", score_cp=40, score_mate=None),  # within 30
            MoveInfo(uci="c2c4", score_cp=10, score_mate=None),  # outside 30
        ]
        result = filter_candidates(candidates, GamePhase.OPENING)
        assert len(result) == 2
        ucis = [m.uci for m in result]
        assert "e2e4" in ucis
        assert "d2d4" in ucis
        assert "c2c4" not in ucis

    def test_filters_by_threshold_middlegame(self):
        candidates = [
            MoveInfo(uci="e2e4", score_cp=100, score_mate=None),
            MoveInfo(uci="d2d4", score_cp=50, score_mate=None),   # within 75
            MoveInfo(uci="c2c4", score_cp=20, score_mate=None),   # outside 75
        ]
        result = filter_candidates(candidates, GamePhase.MIDDLEGAME)
        assert len(result) == 2

    def test_always_keeps_best(self):
        candidates = [
            MoveInfo(uci="e2e4", score_cp=100, score_mate=None),
        ]
        result = filter_candidates(candidates, GamePhase.ENDGAME)
        assert len(result) == 1
        assert result[0].uci == "e2e4"

    def test_handles_mate_scores(self):
        candidates = [
            MoveInfo(uci="d8h4", score_cp=None, score_mate=2),
            MoveInfo(uci="e2e4", score_cp=50, score_mate=None),
        ]
        result = filter_candidates(candidates, GamePhase.MIDDLEGAME)
        # Mate in 2 = 9998, e4 = 50 — way outside threshold
        assert len(result) == 1
        assert result[0].uci == "d8h4"

    def test_empty_candidates_returns_empty(self):
        result = filter_candidates([], GamePhase.OPENING)
        assert result == []

    def test_endgame_tight_threshold(self):
        candidates = [
            MoveInfo(uci="e1e2", score_cp=30, score_mate=None),
            MoveInfo(uci="e1d2", score_cp=15, score_mate=None),  # within 20
            MoveInfo(uci="e1f1", score_cp=5, score_mate=None),   # outside 20
        ]
        result = filter_candidates(candidates, GamePhase.ENDGAME)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# TestSelectOpponentMove
# ---------------------------------------------------------------------------


class TestSelectOpponentMove:
    async def test_returns_top_engine_move(self):
        engine = AsyncMock()
        engine.best_moves = AsyncMock(return_value=[
            MoveInfo(uci="e7e5", score_cp=-10, score_mate=None),
            MoveInfo(uci="d7d5", score_cp=-15, score_mate=None),
        ])
        board = chess.Board()
        result = await select_opponent_move(board, engine)
        assert result.uci == "e7e5"
        assert result.method == "engine"
        assert result.phase == GamePhase.OPENING

    async def test_raises_on_no_moves(self):
        engine = AsyncMock()
        engine.best_moves = AsyncMock(return_value=[])
        board = chess.Board()
        with pytest.raises(RuntimeError, match="no moves"):
            await select_opponent_move(board, engine)

    async def test_phase_is_detected(self):
        engine = AsyncMock()
        engine.best_moves = AsyncMock(return_value=[
            MoveInfo(uci="e1e2", score_cp=5, score_mate=None),
        ])
        # Endgame position
        board = chess.Board("4k3/5ppp/8/8/8/8/5PPP/4K2R w K - 0 30")
        result = await select_opponent_move(board, engine)
        assert result.phase == GamePhase.ENDGAME

    async def test_llm_selection_used_when_multiple_candidates(self):
        """When LLM returns a valid selection, it should be used."""
        engine = AsyncMock()
        # Middlegame position: both sides fully developed, queens present
        board = chess.Board(
            "r2q1rk1/ppp1bppp/2np1n2/4p3/2B1P1b1/2NP1N2/PPP2PPP/R1BQ1RK1 b - - 0 10"
        )
        engine.best_moves = AsyncMock(return_value=[
            MoveInfo(uci="d6d5", score_cp=-5, score_mate=None),
            MoveInfo(uci="a7a6", score_cp=-20, score_mate=None),
            MoveInfo(uci="b7b5", score_cp=-30, score_mate=None),
        ])
        teacher = AsyncMock()
        teacher.select_teaching_move = AsyncMock(return_value=("a6", "develops queenside play"))

        result = await select_opponent_move(board, engine, teacher=teacher)
        assert result.uci == "a7a6"
        assert result.method == "llm"
        assert result.reason == "develops queenside play"
        teacher.select_teaching_move.assert_called_once()

    async def test_fallback_on_llm_failure(self):
        """When LLM returns None, fall back to top engine move."""
        engine = AsyncMock()
        board = chess.Board(
            "r2q1rk1/ppp1bppp/2np1n2/4p3/2B1P1b1/2NP1N2/PPP2PPP/R1BQ1RK1 b - - 0 10"
        )
        engine.best_moves = AsyncMock(return_value=[
            MoveInfo(uci="d6d5", score_cp=-5, score_mate=None),
            MoveInfo(uci="a7a6", score_cp=-20, score_mate=None),
        ])
        teacher = AsyncMock()
        teacher.select_teaching_move = AsyncMock(return_value=None)

        result = await select_opponent_move(board, engine, teacher=teacher)
        assert result.uci == "d6d5"
        assert result.method == "engine"

    async def test_endgame_skips_llm(self):
        """In endgame, LLM is never consulted."""
        engine = AsyncMock()
        board = chess.Board("4k3/5ppp/8/8/8/8/5PPP/4K2R w K - 0 30")
        engine.best_moves = AsyncMock(return_value=[
            MoveInfo(uci="h1h8", score_cp=200, score_mate=None),
            MoveInfo(uci="e1e2", score_cp=195, score_mate=None),
        ])
        teacher = AsyncMock()

        result = await select_opponent_move(board, engine, teacher=teacher)
        assert result.method == "engine"
        teacher.select_teaching_move.assert_not_called()

    async def test_single_candidate_skips_llm(self):
        """When only one candidate survives filtering, skip LLM."""
        engine = AsyncMock()
        board = chess.Board()
        engine.best_moves = AsyncMock(return_value=[
            MoveInfo(uci="e7e5", score_cp=-10, score_mate=None),
            MoveInfo(uci="a7a6", score_cp=-100, score_mate=None),  # way outside threshold
        ])
        teacher = AsyncMock()

        result = await select_opponent_move(board, engine, teacher=teacher)
        assert result.method == "engine"
        teacher.select_teaching_move.assert_not_called()
