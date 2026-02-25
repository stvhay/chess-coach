"""Tactical motif detection: pins, forks, skewers, hanging pieces, and more."""

import chess

from server.analysis.tactics.types import (
    BackRankWeakness,
    CapturableDefender,
    DiscoveredAttack,
    DoubleCheck,
    ExposedKing,
    Fork,
    HangingPiece,
    MatePattern,
    MateThreat,
    OverloadedPiece,
    Pin,
    PieceInvolvement,
    Skewer,
    TacticValue,
    TacticalMotifs,
    TrappedPiece,
    XRayAttack,
    XRayDefense,
    index_by_piece,
)
from server.analysis.tactics.see import see
from server.analysis.tactics.rays import _find_ray_motifs
from server.analysis.tactics.finders import (
    _can_defend,
    _find_back_rank_weaknesses,
    _find_capturable_defenders,
    _find_double_checks,
    _find_exposed_kings,
    _find_forks,
    _find_hanging,
    _find_mate_patterns,
    _find_mate_threats,
    _find_overloaded_pieces,
    _find_trapped_pieces,
)
from server.analysis.tactics.valuation import (
    _value_capturable_defender,
    _value_discovered,
    _value_fork,
    _value_hanging,
    _value_overloaded,
    _value_pin,
    _value_skewer,
)

__all__ = [
    "Pin",
    "Fork",
    "Skewer",
    "HangingPiece",
    "DiscoveredAttack",
    "DoubleCheck",
    "TrappedPiece",
    "MatePattern",
    "MateThreat",
    "BackRankWeakness",
    "XRayAttack",
    "XRayDefense",
    "ExposedKing",
    "OverloadedPiece",
    "CapturableDefender",
    "TacticValue",
    "TacticalMotifs",
    "PieceInvolvement",
    "index_by_piece",
    "analyze_tactics",
    "see",
    "_can_defend",
]


def analyze_tactics(board: chess.Board) -> TacticalMotifs:
    ray = _find_ray_motifs(board)
    mate_threats = _find_mate_threats(board)
    back_rank_weaknesses = _find_back_rank_weaknesses(board)
    motifs = TacticalMotifs(
        pins=ray.pins,
        forks=_find_forks(board, pins=ray.pins),
        skewers=ray.skewers,
        hanging=_find_hanging(board),
        discovered_attacks=ray.discovered_attacks,
        double_checks=_find_double_checks(board),
        trapped_pieces=_find_trapped_pieces(board),
        mate_patterns=_find_mate_patterns(board),
        mate_threats=mate_threats,
        back_rank_weaknesses=back_rank_weaknesses,
        xray_attacks=ray.xray_attacks,
        xray_defenses=ray.xray_defenses,
        exposed_kings=_find_exposed_kings(board),
        overloaded_pieces=_find_overloaded_pieces(
            board,
            back_rank_weaknesses=back_rank_weaknesses,
            mate_threats=mate_threats,
        ),
        capturable_defenders=_find_capturable_defenders(board),
    )

    # Valuation pass: compute TacticValue for each motif
    for h in motifs.hanging:
        h.value = _value_hanging(h, board)
    for p in motifs.pins:
        p.value = _value_pin(p, board)
    for f in motifs.forks:
        f.value = _value_fork(f, board)
    for s in motifs.skewers:
        s.value = _value_skewer(s, board)
    for da in motifs.discovered_attacks:
        da.value = _value_discovered(da, board)
    for cd in motifs.capturable_defenders:
        cd.value = _value_capturable_defender(cd, board)
    for op in motifs.overloaded_pieces:
        op.value = _value_overloaded(op, board)

    # Cross-reference: link hanging pieces to pins via defense_notes
    for h in motifs.hanging:
        if h.value and h.value.defense_notes:
            for p in motifs.pins:
                if p.pinned_square in h.value.defense_notes:
                    h.value.related_motifs.append(
                        f"pin:{p.pinner_square}-{p.pinned_square}-{p.pinned_to}"
                    )

    return motifs
