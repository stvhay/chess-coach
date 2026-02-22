"""Opponent move selection module.

Extracts opponent move logic from the game loop. Detects game phase,
filters Stockfish candidates by centipawn threshold, and optionally
delegates to the LLM for pedagogically-motivated selection.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

import chess

from server.analysis import STARTING_MINORS, analyze, analyze_material, summarize_position
from server.engine import EngineAnalysis, MoveInfo
from server.llm import ChessTeacher, OpponentMoveContext


class GamePhase(enum.Enum):
    OPENING = "opening"
    MIDDLEGAME = "middlegame"
    ENDGAME = "endgame"


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


def _count_developed(board: chess.Board, color: chess.Color) -> int:
    """Count how many minor pieces have moved from starting squares."""
    developed = 0
    for sq, pt in STARTING_MINORS[color]:
        piece = board.piece_at(sq)
        if piece is None or piece.color != color or piece.piece_type != pt:
            developed += 1
    return developed


def detect_game_phase(board: chess.Board) -> GamePhase:
    """Detect the current game phase from board state.

    Opening: move <= 15 AND (either side < 3 minors developed OR no captures)
    Endgame: no queens OR both sides <= 13 material points
    Middlegame: everything else
    """
    mat = analyze_material(board)

    # Endgame: no queens on the board, or both sides have low material
    if mat.white.queens == 0 and mat.black.queens == 0:
        return GamePhase.ENDGAME
    if mat.white_total <= 13 and mat.black_total <= 13:
        return GamePhase.ENDGAME

    # Opening: early moves with undeveloped pieces
    if board.fullmove_number <= 15:
        w_dev = _count_developed(board, chess.WHITE)
        b_dev = _count_developed(board, chess.BLACK)
        if w_dev < 3 or b_dev < 3:
            return GamePhase.OPENING

    return GamePhase.MIDDLEGAME


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
    summary = summarize_position(report)

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
