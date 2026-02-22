"""Two-pass screen/validate coaching pipeline.

Orchestrates: screen → annotate → rank → validate → format.
Produces a fully grounded CoachingContext for the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from server.annotator import AnnotatedLine, annotate_lines, build_annotated_line
from server.elo_profiles import EloProfile
from server.engine import EngineAnalysis, Evaluation, LineInfo


@dataclass
class CoachingContext:
    """Everything the LLM needs, fully grounded in computed facts."""
    player_move: AnnotatedLine | None = None   # annotated line starting from played move
    best_lines: list[AnnotatedLine] = field(default_factory=list)  # top validated alternatives
    quality: str = ""                   # blunder/mistake/inaccuracy/brilliant
    cp_loss: int = 0
    player_color: str = ""
    rag_context: str = ""


def rank_by_teachability(
    lines: list[AnnotatedLine],
    max_concept_depth: int = 4,
    student_is_white: bool = True,
) -> list[AnnotatedLine]:
    """Score lines by pedagogical interest. Sets interest_score on each line.

    Scoring heuristic (v1 -- designed to be replaced by trained model later):
    - Line contains checkmate for student: +100 (absolute priority)
    - Line contains checkmate for opponent: -50 (bad line)
    - Named mate pattern (back_rank, smothered, etc.): +5
    - Trapped piece in reachable depth: +3
    - Double check in reachable depth: +3
    - Other tactic appears within max_concept_depth: +3 per motif type
    - Simple material gain (hanging piece captured): +2
    - Clear positional theme (passed pawn, open file): +1
    - Requires deep calc to justify (motifs only after max_concept_depth): -2
    - Large eval loss vs best move (>150cp worse): -3

    score_mate is always from White's perspective. student_is_white controls
    how we interpret it.
    """
    if not lines:
        return lines

    # Find the best score for relative comparison
    best_cp = None
    for line in lines:
        if line.score_cp is not None:
            if best_cp is None or line.score_cp > best_cp:
                best_cp = line.score_cp

    for line in lines:
        score = 0.0

        early_motifs: set[str] = set()
        late_motifs: set[str] = set()

        for ann in line.annotations:
            if ann.ply < max_concept_depth:
                early_motifs.update(ann.new_motifs)
                # Material gain from captures
                if ann.material_change > 50:
                    score += 2.0
            else:
                late_motifs.update(ann.new_motifs)

        # Checkmate — absolute priority, but only when the STUDENT delivers it.
        # score_mate is from White's perspective: positive = White mates,
        # negative = Black mates.
        if "checkmate" in early_motifs or "checkmate" in late_motifs:
            if line.score_mate is not None:
                student_mates = (
                    (student_is_white and line.score_mate > 0) or
                    (not student_is_white and line.score_mate < 0)
                )
                if student_mates:
                    score += 100.0
                else:
                    # Opponent delivers checkmate — bad line for student
                    score -= 50.0
            else:
                # score_mate is None but checkmate detected in annotations
                score += 100.0

        # High-value motifs get bonus scoring
        HIGH_VALUE_MOTIFS = {"double_check", "trapped_piece"}
        MATE_PATTERN_PREFIX = "mate_"
        for motif in early_motifs:
            if motif.startswith(MATE_PATTERN_PREFIX):
                score += 5.0
            elif motif in HIGH_VALUE_MOTIFS:
                score += 3.0

        # All tactics in reachable depth (including high-value, stacks with above)
        score += 3.0 * len(early_motifs)

        # Positional themes (detected via summary keywords)
        for ann in line.annotations[:max_concept_depth]:
            summary_lower = ann.position_summary.lower()
            if "passed pawn" in summary_lower:
                score += 1.0
                break
            if "open file" in summary_lower:
                score += 1.0
                break
            if "isolated" in summary_lower:
                score += 1.0
                break

        # Penalty: motifs only appear deep
        only_deep = late_motifs - early_motifs
        score -= 2.0 * len(only_deep)

        # Penalty: large eval loss vs best
        if best_cp is not None and line.score_cp is not None:
            loss = best_cp - line.score_cp
            if loss > 150:
                score -= 3.0

        line.interest_score = score

    return sorted(lines, key=lambda l: l.interest_score, reverse=True)


async def screen_and_validate(
    engine: EngineAnalysis,
    board_before: chess.Board,
    player_move_uci: str,
    eval_before: Evaluation,
    profile: EloProfile,
) -> CoachingContext:
    """Two-pass coaching pipeline.

    Pass 1 (screen): Wide shallow search for candidate moves.
    Pass 2 (validate): Deep search on top teachable candidates.
    Returns fully annotated coaching context.
    """
    ctx = CoachingContext()
    fen = board_before.fen()

    # --- Pass 1: Screen ---
    screen_lines = await engine.analyze_lines(
        fen, n=profile.screen_breadth, depth=profile.screen_depth
    )
    if not screen_lines:
        return ctx

    # Annotate all screen lines
    annotated = annotate_lines(
        board_before, screen_lines, max_ply=profile.max_concept_depth
    )

    # Rank by teachability and take top candidates
    student_is_white = board_before.turn == chess.WHITE
    ranked = rank_by_teachability(
        annotated,
        max_concept_depth=profile.max_concept_depth,
        student_is_white=student_is_white,
    )
    top_candidates = ranked[:profile.validate_breadth]

    # --- Pass 2: Validate ---
    validated: list[AnnotatedLine] = []
    for candidate in top_candidates:
        # Push candidate move and do a deep eval
        temp = board_before.copy()
        try:
            move = chess.Move.from_uci(candidate.first_move_uci)
            if move not in temp.legal_moves:
                continue
        except (ValueError, chess.InvalidMoveError):
            continue
        temp.push(move)

        deep_eval = await engine.evaluate(temp.fen(), depth=profile.validate_depth)
        # Build a LineInfo from the deep eval's PV
        if deep_eval.pv:
            deep_line = LineInfo(
                uci=candidate.first_move_uci,
                san=candidate.first_move_san,
                score_cp=deep_eval.score_cp,
                score_mate=deep_eval.score_mate,
                pv=[candidate.first_move_uci] + deep_eval.pv,
                depth=deep_eval.depth,
            )
            validated_line = build_annotated_line(
                board_before, deep_line, max_ply=profile.recommend_depth
            )
            validated_line.interest_score = candidate.interest_score
            validated.append(validated_line)
        else:
            # Use the screen-pass annotation if deep eval has no PV
            validated.append(candidate)

    ctx.best_lines = validated

    # --- Annotate the player's actual move ---
    try:
        player_move = chess.Move.from_uci(player_move_uci)
        if player_move in board_before.legal_moves:
            temp = board_before.copy()
            temp.push(player_move)
            player_eval = await engine.evaluate(
                temp.fen(), depth=profile.validate_depth
            )
            player_pv = [player_move_uci] + (player_eval.pv or [])
            player_line = LineInfo(
                uci=player_move_uci,
                san=board_before.san(player_move),
                score_cp=player_eval.score_cp,
                score_mate=player_eval.score_mate,
                pv=player_pv,
                depth=player_eval.depth,
            )
            ctx.player_move = build_annotated_line(
                board_before, player_line, max_ply=profile.max_concept_depth
            )
    except (ValueError, chess.InvalidMoveError):
        pass

    return ctx
