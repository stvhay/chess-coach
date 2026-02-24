"""Opponent move selection module.

Extracts opponent move logic from the game loop. Detects game phase,
filters Stockfish candidates by centipawn threshold, and optionally
delegates to the LLM for pedagogically-motivated selection.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from server.analysis import GamePhase, analyze, detect_game_phase
from server.descriptions import describe_position_from_report
from server.engine import EngineAnalysis, MoveInfo
from server.llm import ChessTeacher, OpponentMoveContext


# Centipawn thresholds per phase — moves within this delta of the best
# candidate are considered acceptable.
OPENING_CP_THRESHOLD = 30
MIDDLEGAME_CP_THRESHOLD = 75
ENDGAME_CP_THRESHOLD = 20

CANDIDATE_COUNT = 5
SELECTION_DEPTH = 12


@dataclass
class OpponentMoveResult:
    uci: str
    san: str
    phase: GamePhase
    reason: str | None = None   # LLM's rationale (for logging)
    method: str = "engine"      # "llm" or "engine"


def _cp_threshold(phase: GamePhase) -> int:
    """Return the centipawn tolerance for the given phase."""
    if phase == GamePhase.OPENING:
        return OPENING_CP_THRESHOLD
    if phase == GamePhase.MIDDLEGAME:
        return MIDDLEGAME_CP_THRESHOLD
    return ENDGAME_CP_THRESHOLD


def _score_value(move: MoveInfo) -> int:
    """Extract a comparable centipawn value from a MoveInfo.

    Mate scores are mapped to large values so they sort correctly.
    """
    if move.score_mate is not None:
        if move.score_mate > 0:
            return 10_000 - move.score_mate
        return -10_000 - move.score_mate
    if move.score_cp is not None:
        return move.score_cp
    return 0


def filter_candidates(
    candidates: list[MoveInfo], phase: GamePhase
) -> list[MoveInfo]:
    """Keep moves within epsilon cp of the best. Always returns at least 1."""
    if not candidates:
        return candidates
    threshold = _cp_threshold(phase)
    best_score = _score_value(candidates[0])
    filtered = [
        m for m in candidates
        if abs(_score_value(m) - best_score) <= threshold
    ]
    # Safety: always return at least the best move
    if not filtered:
        filtered = [candidates[0]]
    return filtered


async def select_opponent_move(
    board: chess.Board,
    engine: EngineAnalysis,
    teacher: ChessTeacher | None = None,
) -> OpponentMoveResult:
    """Select an opponent move using engine candidates + optional LLM.

    When teacher is None, only one candidate survives filtering, or the
    game is in the endgame, returns the top engine move. Otherwise
    delegates to the LLM for pedagogically-motivated selection.
    """
    fen = board.fen()
    phase = detect_game_phase(board)

    candidates = await engine.best_moves(fen, n=CANDIDATE_COUNT, depth=SELECTION_DEPTH)
    if not candidates:
        raise RuntimeError("Engine returned no moves")

    filtered = filter_candidates(candidates, phase)
    best = filtered[0]

    def _make_result(move_info: MoveInfo, method: str = "engine", reason: str | None = None):
        move_obj = chess.Move.from_uci(move_info.uci)
        return OpponentMoveResult(
            uci=move_info.uci,
            san=board.san(move_obj),
            phase=phase,
            reason=reason,
            method=method,
        )

    # Skip LLM for: single candidate, no teacher, or endgame precision
    if len(filtered) <= 1 or teacher is None or phase == GamePhase.ENDGAME:
        return _make_result(best)

    # Build context for LLM selection
    report = analyze(board)
    student_is_white = board.turn != chess.WHITE  # student is the side NOT about to move
    pos_desc = describe_position_from_report(report, student_is_white)
    summary = pos_desc.as_text()

    # Determine player color (opponent is the other side)
    player_color = "White" if board.turn == chess.BLACK else "Black"

    candidate_dicts = [
        {"san": board.san(chess.Move.from_uci(m.uci)), "uci": m.uci, "score_cp": m.score_cp}
        for m in filtered
    ]

    ctx = OpponentMoveContext(
        fen=fen,
        game_phase=phase.value,
        position_summary=summary,
        candidates=candidate_dicts,
        player_color=player_color,
    )

    result = await teacher.select_teaching_move(ctx)
    if result is not None:
        selected_san, reason = result
        # Find matching candidate by SAN
        for m in filtered:
            move_obj = chess.Move.from_uci(m.uci)
            if board.san(move_obj) == selected_san:
                return _make_result(m, method="llm", reason=reason)

    # Fallback: top engine move
    return _make_result(best)
