"""Tactical motif types: dataclasses, containers, and shared constants."""

from dataclasses import dataclass, field

import chess

from server.analysis.constants import get_piece_value  # noqa: F401 — re-exported for rays/finders


@dataclass
class TacticValue:
    """Material value of a tactic if exploited."""
    material_delta: int    # centipawns (100 = 1 pawn), positive = beneficiary gains
    is_sound: bool         # material_delta > 0
    source: str = "see"    # "see" | "engine" | "heuristic"


@dataclass
class Pin:
    pinned_square: str
    pinned_piece: str
    pinner_square: str
    pinner_piece: str
    pinned_to: str  # square of the piece being shielded (king, queen, etc.)
    pinned_to_piece: str = ""  # piece symbol on pinned_to square (e.g. "K", "q")
    is_absolute: bool = False  # pinned to king (piece cannot legally move)
    color: str = ""  # "white" or "black" — color of the pinner
    value: TacticValue | None = None


@dataclass
class Fork:
    forking_square: str
    forking_piece: str
    targets: list[str]  # squares being forked
    target_pieces: list[str] = field(default_factory=list)  # piece chars on target squares
    color: str = ""  # "white" or "black" — color of the forking piece
    is_check_fork: bool = False   # one target is the king
    is_royal_fork: bool = False   # targets include both king and queen
    is_pin_fork: bool = False     # forker also pins one of the targets
    value: TacticValue | None = None


@dataclass
class Skewer:
    attacker_square: str
    attacker_piece: str
    front_square: str
    front_piece: str
    behind_square: str
    behind_piece: str
    color: str = ""  # "white" or "black" — color of the attacker
    is_absolute: bool = False  # True when front piece is the king
    value: TacticValue | None = None


@dataclass
class HangingPiece:
    square: str
    piece: str
    attacker_squares: list[str]
    color: str = ""  # "white" or "black" — whose piece is hanging
    can_retreat: bool = True  # piece owner moves next and can save it
    value: TacticValue | None = None


@dataclass
class DiscoveredAttack:
    blocker_square: str
    blocker_piece: str
    slider_square: str
    slider_piece: str
    target_square: str
    target_piece: str
    significance: str = "normal"  # "low" for pawn-reveals-rook x-rays, "normal" otherwise
    color: str = ""  # "white" or "black" — color of the attacking side (slider owner)
    value: TacticValue | None = None


@dataclass
class DoubleCheck:
    checker_squares: list[str]
    color: str = ""  # "white" or "black" — color of the checking side


@dataclass
class TrappedPiece:
    square: str
    piece: str
    color: str = ""  # "white" or "black" — color of the trapped piece


@dataclass
class MatePattern:
    pattern: str  # e.g. "back_rank", "smothered", "arabian", "hook", etc.


@dataclass
class MateThreat:
    threatening_color: str  # "white" or "black"
    mating_square: str      # square where mate would be delivered
    depth: int = 1          # mate-in-N (1 = immediate, 2 = mate-in-2, etc.)
    mating_move: str | None = None  # SAN of the key mating move (if known)


@dataclass
class BackRankWeakness:
    weak_color: str  # "white" or "black" — whose back rank is vulnerable
    king_square: str


@dataclass
class XRayAttack:
    slider_square: str
    slider_piece: str
    through_square: str  # enemy piece being x-rayed through
    through_piece: str
    target_square: str   # valuable target behind
    target_piece: str
    color: str = ""  # "white" or "black" — color of the slider


@dataclass
class XRayDefense:
    slider_square: str
    slider_piece: str
    through_square: str   # enemy piece between slider and defended piece
    through_piece: str
    defended_square: str   # friendly piece being defended through the enemy
    defended_piece: str
    color: str = ""  # "white" or "black" — color of the slider


@dataclass
class ExposedKing:
    color: str  # "white" or "black" — whose king is exposed
    king_square: str


@dataclass
class OverloadedPiece:
    square: str
    piece: str
    defended_squares: list[str]  # attacked targets this piece sole-defends
    color: str = ""  # "white" or "black" — color of the overloaded piece
    value: TacticValue | None = None


@dataclass
class CapturableDefender:
    defender_square: str
    defender_piece: str
    charge_square: str   # piece being defended
    charge_piece: str
    attacker_square: str  # who can capture the defender
    color: str = ""  # "white" or "black" — color of the defender
    value: TacticValue | None = None


@dataclass
class TacticalMotifs:
    pins: list[Pin] = field(default_factory=list)
    forks: list[Fork] = field(default_factory=list)
    skewers: list[Skewer] = field(default_factory=list)
    hanging: list[HangingPiece] = field(default_factory=list)
    discovered_attacks: list[DiscoveredAttack] = field(default_factory=list)
    double_checks: list[DoubleCheck] = field(default_factory=list)
    trapped_pieces: list[TrappedPiece] = field(default_factory=list)
    mate_patterns: list[MatePattern] = field(default_factory=list)
    mate_threats: list[MateThreat] = field(default_factory=list)
    back_rank_weaknesses: list[BackRankWeakness] = field(default_factory=list)
    xray_attacks: list[XRayAttack] = field(default_factory=list)
    xray_defenses: list[XRayDefense] = field(default_factory=list)
    exposed_kings: list[ExposedKing] = field(default_factory=list)
    overloaded_pieces: list[OverloadedPiece] = field(default_factory=list)
    capturable_defenders: list[CapturableDefender] = field(default_factory=list)


@dataclass
class PieceInvolvement:
    motif_type: str   # "pin", "fork", "skewer", "hanging", etc.
    role: str         # "attacker", "target", "defender", "pinned", "blocker"
    motif_index: int  # index into the relevant list in TacticalMotifs


def index_by_piece(tactics: TacticalMotifs) -> dict[str, list[PieceInvolvement]]:
    """Build square -> motif involvement mapping from all detected tactics."""
    idx: dict[str, list[PieceInvolvement]] = {}

    def _add(square: str, motif_type: str, role: str, motif_index: int) -> None:
        idx.setdefault(square, []).append(
            PieceInvolvement(motif_type=motif_type, role=role, motif_index=motif_index)
        )

    for i, pin in enumerate(tactics.pins):
        _add(pin.pinner_square, "pin", "attacker", i)
        _add(pin.pinned_square, "pin", "pinned", i)
        _add(pin.pinned_to, "pin", "target", i)

    for i, fork in enumerate(tactics.forks):
        _add(fork.forking_square, "fork", "attacker", i)
        for t in fork.targets:
            _add(t, "fork", "target", i)

    for i, skewer in enumerate(tactics.skewers):
        _add(skewer.attacker_square, "skewer", "attacker", i)
        _add(skewer.front_square, "skewer", "target", i)
        _add(skewer.behind_square, "skewer", "target", i)

    for i, h in enumerate(tactics.hanging):
        _add(h.square, "hanging", "target", i)
        for a in h.attacker_squares:
            _add(a, "hanging", "attacker", i)

    for i, da in enumerate(tactics.discovered_attacks):
        _add(da.blocker_square, "discovered_attack", "blocker", i)
        _add(da.slider_square, "discovered_attack", "attacker", i)
        _add(da.target_square, "discovered_attack", "target", i)

    for i, dc in enumerate(tactics.double_checks):
        for sq in dc.checker_squares:
            _add(sq, "double_check", "attacker", i)

    for i, tp in enumerate(tactics.trapped_pieces):
        _add(tp.square, "trapped", "target", i)

    # MatePattern has no square fields - skip

    for i, mt in enumerate(tactics.mate_threats):
        _add(mt.mating_square, "mate_threat", "target", i)

    for i, br in enumerate(tactics.back_rank_weaknesses):
        _add(br.king_square, "back_rank_weakness", "target", i)

    for i, xa in enumerate(tactics.xray_attacks):
        _add(xa.slider_square, "xray_attack", "attacker", i)
        _add(xa.through_square, "xray_attack", "target", i)
        _add(xa.target_square, "xray_attack", "target", i)

    for i, xd in enumerate(tactics.xray_defenses):
        _add(xd.slider_square, "xray_defense", "defender", i)
        _add(xd.through_square, "xray_defense", "target", i)
        _add(xd.defended_square, "xray_defense", "defended", i)

    for i, ek in enumerate(tactics.exposed_kings):
        _add(ek.king_square, "exposed_king", "target", i)

    for i, op in enumerate(tactics.overloaded_pieces):
        _add(op.square, "overloaded", "target", i)
        for ds in op.defended_squares:
            _add(ds, "overloaded", "defended", i)

    for i, cd in enumerate(tactics.capturable_defenders):
        _add(cd.defender_square, "capturable_defender", "defender", i)
        _add(cd.charge_square, "capturable_defender", "defended", i)
        _add(cd.attacker_square, "capturable_defender", "attacker", i)

    return idx


@dataclass
class _RayMotifs:
    """Internal result container for unified ray detection."""
    pins: list[Pin]
    skewers: list[Skewer]
    xray_attacks: list[XRayAttack]
    xray_defenses: list[XRayDefense]
    discovered_attacks: list[DiscoveredAttack]


_ORTHOGONAL = [(0, 1), (0, -1), (1, 0), (-1, 0)]
_DIAGONAL = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

_RAY_DIRS: dict[chess.PieceType, list[tuple[int, int]]] = {
    chess.ROOK: _ORTHOGONAL,
    chess.BISHOP: _DIAGONAL,
    chess.QUEEN: _ORTHOGONAL + _DIAGONAL,
}
