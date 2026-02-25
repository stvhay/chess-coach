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
    TacticalMotifs,
    TrappedPiece,
    XRayAttack,
    XRayDefense,
    index_by_piece,
)
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
    "TacticalMotifs",
    "PieceInvolvement",
    "index_by_piece",
    "analyze_tactics",
    "_can_defend",
]


def analyze_tactics(board: chess.Board) -> TacticalMotifs:
    ray = _find_ray_motifs(board)
    mate_threats = _find_mate_threats(board)
    back_rank_weaknesses = _find_back_rank_weaknesses(board)
    return TacticalMotifs(
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
