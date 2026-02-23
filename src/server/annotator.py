"""Line annotation module.

Pure functions that walk PV lines and annotate each ply with tactical
and positional features. No engine calls — takes pre-computed PV data.
Reusable for coaching, game review, and pedagogical decision trees.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from server.analysis import (
    TacticalMotifs,
    analyze_material,
    analyze_tactics,
    summarize_position,
    analyze,
)
from server.engine import LineInfo


@dataclass
class PlyAnnotation:
    """Annotation for a single position within a PV line."""
    ply: int                        # 0-indexed within the line
    fen: str
    move_san: str
    tactics: TacticalMotifs
    material_change: int            # cp gained/lost this ply
    new_motifs: list[str]           # motifs that appeared THIS ply (not before)
    position_summary: str           # 1-sentence from summarize_position()
    is_check: bool = False          # position is in check after this move
    is_checkmate: bool = False      # position is checkmate after this move


@dataclass
class AnnotatedLine:
    """A PV line with per-ply tactical annotations."""
    first_move_san: str
    first_move_uci: str
    score_cp: int | None
    score_mate: int | None
    pv_san: list[str]               # full PV in SAN
    annotations: list[PlyAnnotation] = field(default_factory=list)
    interest_score: float = 0.0     # pedagogical interest (set by ranker)
    has_sacrifice: bool = False     # material dip followed by recovery or mate


def _motif_set(tactics: TacticalMotifs, board: chess.Board | None = None) -> set[str]:
    """Extract a set of motif type labels from a TacticalMotifs instance."""
    motifs: set[str] = set()
    if tactics.pins:
        motifs.add("pin")
    if tactics.forks:
        motifs.add("fork")
    if tactics.skewers:
        motifs.add("skewer")
    if tactics.hanging:
        motifs.add("hanging_piece")
    if tactics.discovered_attacks:
        motifs.add("discovered_attack")
    if tactics.double_checks:
        motifs.add("double_check")
    if tactics.trapped_pieces:
        motifs.add("trapped_piece")
    for mp in tactics.mate_patterns:
        motifs.add(f"mate_{mp.pattern}")
    if tactics.mate_threats:
        motifs.add("mate_threat")
    if tactics.back_rank_weaknesses:
        motifs.add("back_rank_weakness")
    if tactics.xray_attacks:
        motifs.add("xray_attack")
    if tactics.exposed_kings:
        motifs.add("exposed_king")
    if tactics.overloaded_pieces:
        motifs.add("overloaded_piece")
    if tactics.capturable_defenders:
        motifs.add("capturable_defender")
    if board is not None and board.is_checkmate():
        motifs.add("checkmate")
    return motifs


def _material_cp(board: chess.Board) -> int:
    """Total material in centipawns from White's perspective."""
    mat = analyze_material(board)
    return (mat.white_total - mat.black_total) * 100


def annotate_line(
    board: chess.Board,
    pv_uci: list[str],
    max_ply: int = 6,
    cache: dict[str, TacticalMotifs] | None = None,
) -> list[PlyAnnotation]:
    """Walk a PV line, annotating each ply with tactical features.

    Uses optional cache dict keyed by FEN to avoid redundant analysis
    across lines that share transpositions.
    """
    if cache is None:
        cache = {}

    annotations: list[PlyAnnotation] = []
    temp = board.copy()
    prev_material = _material_cp(temp)
    prev_motifs: set[str] = _motif_set(
        cache.get(temp.fen()) or analyze_tactics(temp), temp
    )

    for i, uci in enumerate(pv_uci[:max_ply]):
        try:
            move = chess.Move.from_uci(uci)
            if move not in temp.legal_moves:
                break
        except (ValueError, chess.InvalidMoveError):
            break

        move_san = temp.san(move)
        temp.push(move)
        fen = temp.fen()

        # Get or compute tactics for this position
        if fen in cache:
            tactics = cache[fen]
        else:
            tactics = analyze_tactics(temp)
            cache[fen] = tactics

        current_material = _material_cp(temp)
        material_change = current_material - prev_material

        current_motifs = _motif_set(tactics, temp)
        new_motifs = sorted(current_motifs - prev_motifs)

        report = analyze(temp)
        summary = summarize_position(report)

        annotations.append(PlyAnnotation(
            ply=i,
            fen=fen,
            move_san=move_san,
            tactics=tactics,
            material_change=material_change,
            new_motifs=new_motifs,
            position_summary=summary,
            is_check=temp.is_check(),
            is_checkmate=temp.is_checkmate(),
        ))

        prev_material = current_material
        prev_motifs = current_motifs

    return annotations


def _detect_sacrifice(annotations: list[PlyAnnotation], score_mate: int | None) -> bool:
    """Detect sacrifice pattern: player gives up 200+ cp then line is still favorable.

    Checks even plies (player moves) for cumulative material loss of 200+ cp
    relative to start. The line must end favorably (checkmate or material recovery).
    """
    if not annotations:
        return False
    cumulative = 0
    max_deficit = 0
    has_checkmate = False
    for ann in annotations:
        cumulative += ann.material_change
        # Player plies are even (0, 2, 4...) — material loss on player ply
        if ann.ply % 2 == 0 and cumulative < max_deficit:
            max_deficit = cumulative
        if "checkmate" in (ann.new_motifs or []):
            has_checkmate = True
    # Sacrifice = gave up 200+ cp AND (recovered or checkmate)
    if max_deficit <= -200:
        if has_checkmate or score_mate is not None:
            return True
        # Material recovered: final cumulative is near or above starting
        if cumulative >= max_deficit + 200:
            return True
    return False


def build_annotated_line(
    board: chess.Board,
    line: LineInfo,
    max_ply: int = 6,
    cache: dict[str, TacticalMotifs] | None = None,
) -> AnnotatedLine:
    """Build an AnnotatedLine from a LineInfo and board state."""
    # Convert full PV to SAN
    temp = board.copy()
    pv_san: list[str] = []
    for uci in line.pv[:max_ply]:
        try:
            move = chess.Move.from_uci(uci)
            if move not in temp.legal_moves:
                break
            pv_san.append(temp.san(move))
            temp.push(move)
        except (ValueError, chess.InvalidMoveError):
            break

    annotations = annotate_line(board, line.pv, max_ply=max_ply, cache=cache)

    return AnnotatedLine(
        first_move_san=line.san,
        first_move_uci=line.uci,
        score_cp=line.score_cp,
        score_mate=line.score_mate,
        pv_san=pv_san,
        annotations=annotations,
        has_sacrifice=_detect_sacrifice(annotations, line.score_mate),
    )


def annotate_lines(
    board: chess.Board,
    lines: list[LineInfo],
    max_ply: int = 6,
) -> list[AnnotatedLine]:
    """Annotate multiple PV lines, sharing a cache across them."""
    cache: dict[str, TacticalMotifs] = {}
    return [
        build_annotated_line(board, line, max_ply=max_ply, cache=cache)
        for line in lines
    ]
