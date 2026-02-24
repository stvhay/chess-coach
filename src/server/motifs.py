"""Motif registry for coaching descriptions.

Consolidates tactical motif rendering, keying, and labeling into a
declarative registry. Each motif type is one MotifSpec entry — adding
a new motif means adding one entry + one render function.

Used by descriptions.py (rendering and diffing) and game_tree.py (labeling).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Callable

import chess

from server.analysis import TacticalMotifs, _colored


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PIECE_NAME: dict[str, str] = {
    "P": "pawn", "N": "knight", "B": "bishop",
    "R": "rook", "Q": "queen", "K": "king",
}


def _own_their(piece_char: str, is_student: bool) -> str:
    """'your knight' or 'their knight' based on ownership."""
    name = _PIECE_NAME[piece_char.upper()]
    return f"your {name}" if is_student else f"their {name}"


def _piece_is_students(piece_char: str, student_is_white: bool | None) -> bool:
    """Is this piece the student's? Uppercase = White pieces."""
    if student_is_white is None:
        return True
    return piece_char.isupper() == student_is_white


def _color_is_students(color_str: str, player_color: str) -> bool:
    """Is this color string the student's color?"""
    return color_str.lower() == player_color.lower()


def _is_significant_discovery(da) -> bool:
    """Filter out trivial pawn-reveals-rook x-rays."""
    blocker_is_pawn = da.blocker_piece.lower() == "p"
    target_is_valuable = da.target_piece.lower() in ("q", "k", "r")
    return not blocker_is_pawn or target_is_valuable


# ---------------------------------------------------------------------------
# Render context
# ---------------------------------------------------------------------------


class RenderMode(enum.Enum):
    """How the motif is being rendered."""
    OPPORTUNITY = "opportunity"
    THREAT = "threat"
    POSITION = "position"


@dataclass
class RenderContext:
    """Context for motif renderers."""
    student_is_white: bool | None
    player_color: str           # "White" or "Black"
    mode: RenderMode = RenderMode.OPPORTUNITY

    @property
    def is_threat(self) -> bool:
        return self.mode == RenderMode.THREAT

    @property
    def is_position_description(self) -> bool:
        return self.mode == RenderMode.POSITION


@dataclass
class RenderedMotif:
    """A rendered motif description with metadata."""
    text: str
    is_opportunity: bool
    diff_key: str
    priority: int
    target_squares: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Motif renderers
# ---------------------------------------------------------------------------

def render_fork(fork, ctx: RenderContext) -> tuple[str, bool]:
    """Render a fork. Returns (description, is_opportunity).

    Pin-forks get different language: "pins X while also attacking Y"
    instead of "forks X and Y", since the pin is the primary motif.
    """
    is_student = _piece_is_students(fork.forking_piece, ctx.student_is_white)
    forker = _own_their(fork.forking_piece, is_student)
    if fork.target_pieces:
        target_descs = [
            f"{_own_their(tp, _piece_is_students(tp, ctx.student_is_white))} on {sq}"
            for tp, sq in zip(fork.target_pieces, fork.targets)
        ]
        targets = " and ".join(target_descs)
    else:
        targets = ", ".join(fork.targets)

    if fork.is_pin_fork:
        # Pin is the primary motif (rendered separately); describe the additional attack
        non_pinned = [
            f"{_own_their(tp, _piece_is_students(tp, ctx.student_is_white))} on {sq}"
            for tp, sq in zip(fork.target_pieces, fork.targets)
        ] if fork.target_pieces else fork.targets
        # All targets are worth mentioning since the pin constrains the position
        desc = f"{forker.capitalize()} on {fork.forking_square} pins and also attacks {targets}."
    else:
        desc = f"{forker.capitalize()} on {fork.forking_square} forks {targets}."
    if fork.target_pieces and any(tp.upper() == "K" for tp in fork.target_pieces):
        other = [
            _own_their(tp, _piece_is_students(tp, ctx.student_is_white))
            for tp in fork.target_pieces if tp.upper() != "K"
        ]
        if other:
            desc = desc[:-1] + f" — wins {other[0]}."
    return desc, is_student


def render_pin(pin, ctx: RenderContext) -> tuple[str, bool]:
    """Render a pin. Returns (description, is_opportunity)."""
    is_student = _piece_is_students(pin.pinner_piece, ctx.student_is_white)
    pinner = _own_their(pin.pinner_piece, is_student)
    pinned = _own_their(pin.pinned_piece, _piece_is_students(pin.pinned_piece, ctx.student_is_white))
    if pin.pinned_to_piece:
        to_desc = f"{_own_their(pin.pinned_to_piece, _piece_is_students(pin.pinned_to_piece, ctx.student_is_white))} on {pin.pinned_to}"
    else:
        to_desc = pin.pinned_to
    abs_label = " — it cannot move" if pin.is_absolute else ""
    desc = (f"{pinner.capitalize()} on {pin.pinner_square} pins "
            f"{pinned} on {pin.pinned_square} to {to_desc}{abs_label}.")
    return desc, is_student


def render_skewer(skewer, ctx: RenderContext) -> tuple[str, bool]:
    """Render a skewer."""
    is_student = _piece_is_students(skewer.attacker_piece, ctx.student_is_white)
    attacker = _own_their(skewer.attacker_piece, is_student)
    front = _own_their(skewer.front_piece, _piece_is_students(skewer.front_piece, ctx.student_is_white))
    behind = _own_their(skewer.behind_piece, _piece_is_students(skewer.behind_piece, ctx.student_is_white))
    desc = (f"{attacker.capitalize()} on {skewer.attacker_square} skewers "
            f"{front} on {skewer.front_square} behind "
            f"{behind} on {skewer.behind_square}.")
    return desc, is_student


def render_hanging(hp, ctx: RenderContext) -> tuple[str, bool]:
    """Render a hanging piece."""
    if hp.color:
        is_opponents = not _color_is_students(hp.color, ctx.player_color)
    else:
        is_opponents = not _piece_is_students(hp.piece, ctx.student_is_white)
    is_students_piece = not is_opponents
    piece_desc = _own_their(hp.piece, is_students_piece)
    if hp.can_retreat:
        desc = f"{piece_desc.capitalize()} on {hp.square} is undefended."
    elif is_opponents:
        desc = f"{piece_desc.capitalize()} on {hp.square} is hanging."
    else:
        desc = f"{piece_desc.capitalize()} on {hp.square} is undefended."
    return desc, is_opponents


def render_discovered_attack(da, ctx: RenderContext) -> tuple[str, bool]:
    """Render a discovered attack.

    In position context uses "x-ray alignment" since nothing has been
    "discovered" yet. In change context uses "discovered attack".
    """
    is_student = _piece_is_students(da.slider_piece, ctx.student_is_white)
    slider = _own_their(da.slider_piece, is_student)
    blocker = _own_their(da.blocker_piece, _piece_is_students(da.blocker_piece, ctx.student_is_white))
    target = _own_their(da.target_piece, _piece_is_students(da.target_piece, ctx.student_is_white))
    if ctx.is_position_description:
        desc = (f"X-ray alignment: {slider} on {da.slider_square} "
                f"behind {blocker} on {da.blocker_square} toward "
                f"{target} on {da.target_square}.")
    else:
        desc = (f"Discovered attack: {blocker} on {da.blocker_square} "
                f"reveals {slider} on {da.slider_square} targeting "
                f"{target} on {da.target_square}.")
    return desc, is_student


def render_double_check(dc, ctx: RenderContext) -> tuple[str, bool]:
    """Render a double check.

    Uses is_threat from ctx to determine opportunity: at ply 0
    the student delivered it (opportunity), at ply 1+ it's a threat.
    """
    squares = " and ".join(dc.checker_squares)
    desc = f"Double check from {squares}."
    return desc, not ctx.is_threat


def render_trapped_piece(tp, ctx: RenderContext) -> tuple[str, bool]:
    """Render a trapped piece."""
    is_opponents = not _piece_is_students(tp.piece, ctx.student_is_white)
    piece_desc = _own_their(tp.piece, not is_opponents)
    desc = f"{piece_desc.capitalize()} on {tp.square} is trapped."
    return desc, is_opponents


def render_mate_threat(mt, ctx: RenderContext) -> tuple[str, bool]:
    """Render a mate threat."""
    is_student = _color_is_students(mt.threatening_color, ctx.player_color)
    if is_student:
        desc = f"You threaten checkmate on {mt.mating_square}."
    else:
        desc = f"They threaten checkmate on {mt.mating_square}."
    return desc, is_student


def render_back_rank_weakness(bw, ctx: RenderContext) -> tuple[str, bool]:
    """Render a back rank weakness."""
    is_opponents = not _color_is_students(bw.weak_color, ctx.player_color)
    whose = "Their" if is_opponents else "Your"
    desc = f"{whose} back rank is weak (king on {bw.king_square})."
    return desc, is_opponents


def render_xray_attack(xa, ctx: RenderContext) -> tuple[str, bool]:
    """Render an x-ray attack.

    Validates that target is actually an enemy piece (not same side as slider).
    This prevents hallucinations where friendly pieces behind enemy pieces
    are incorrectly described as x-ray targets.
    """
    is_student = _piece_is_students(xa.slider_piece, ctx.student_is_white)
    target_is_student = _piece_is_students(xa.target_piece, ctx.student_is_white)

    # X-ray attack must target an ENEMY piece
    # (slider and target must be opposite sides)
    if is_student == target_is_student:
        # Same side — this is not an x-ray attack, it's an x-ray defense
        # Return empty to suppress rendering
        return "", is_student

    slider = _own_their(xa.slider_piece, is_student)
    through = _own_their(xa.through_piece, _piece_is_students(xa.through_piece, ctx.student_is_white))
    target = _own_their(xa.target_piece, target_is_student)
    desc = (f"{slider.capitalize()} on {xa.slider_square} x-rays through "
            f"{through} on {xa.through_square} targeting "
            f"{target} on {xa.target_square}.")
    return desc, is_student


def render_exposed_king(ek, ctx: RenderContext) -> tuple[str, bool]:
    """Render an exposed king."""
    is_opponents = not _color_is_students(ek.color, ctx.player_color)
    whose = "Their" if is_opponents else "Your"
    desc = f"{whose} king on {ek.king_square} is exposed (advanced, no pawn shield)."
    return desc, is_opponents


def render_overloaded_piece(op, ctx: RenderContext) -> tuple[str, bool]:
    """Render an overloaded piece.

    Note: Board state validation is done in analysis.py _find_overloaded_pieces(),
    which verifies defenders can actually attack all claimed squares and checks
    pin-blindness. This renderer just formats the validated data.
    """
    is_opponents = not _piece_is_students(op.piece, ctx.student_is_white)
    piece_desc = _own_their(op.piece, not is_opponents)
    charges = ", ".join(op.defended_squares)
    desc = (f"{piece_desc.capitalize()} on {op.square} is overloaded, "
            f"sole defender of {charges}.")
    return desc, is_opponents


def render_capturable_defender(cd, ctx: RenderContext) -> tuple[str, bool]:
    """Render a capturable defender."""
    is_opponents = not _piece_is_students(cd.defender_piece, ctx.student_is_white)
    defender = _own_their(cd.defender_piece, not is_opponents)
    charge = _own_their(cd.charge_piece, _piece_is_students(cd.charge_piece, ctx.student_is_white))
    desc = (f"{defender.capitalize()} on {cd.defender_square} "
            f"defends {charge} on {cd.charge_square}")
    if cd.attacker_square:
        desc += f" — if captured, {charge} on {cd.charge_square} is left hanging"
    desc += "."
    return desc, is_opponents


# ---------------------------------------------------------------------------
# Ray deduplication
# ---------------------------------------------------------------------------

def _canonical_ray_key(sq_a: str, sq_b: str) -> tuple[str, str]:
    """Canonical key for a ray — sorted endpoint pair.

    Using sorted endpoints means opposite-direction motifs on the same
    physical ray share a key (e.g. Bg4→Qd1 and Qd1→Bg4).
    """
    return tuple(sorted([sq_a, sq_b]))


def _dedup_ray_motifs(tactics: TacticalMotifs) -> dict[str, list]:
    """Remove geometric duplicates among pins, skewers, x-rays, and discovered attacks.

    Groups by canonical ray endpoints and keeps highest priority:
    absolute pin (0) > non-absolute pin (1) > skewer (2) > x-ray (3) > discovered (4).

    Returns dict with keys "pins", "skewers", "xray_attacks",
    "discovered_attacks" -> filtered lists.
    """
    groups: dict[tuple[str, str], list[tuple[int, str, object]]] = {}

    for pin in tactics.pins:
        key = _canonical_ray_key(pin.pinner_square, pin.pinned_to)
        priority = 0 if pin.is_absolute else 1
        groups.setdefault(key, []).append((priority, "pins", pin))

    for skewer in tactics.skewers:
        key = _canonical_ray_key(skewer.attacker_square, skewer.behind_square)
        groups.setdefault(key, []).append((2, "skewers", skewer))

    for xa in tactics.xray_attacks:
        key = _canonical_ray_key(xa.slider_square, xa.target_square)
        groups.setdefault(key, []).append((3, "xray_attacks", xa))

    for da in tactics.discovered_attacks:
        key = _canonical_ray_key(da.slider_square, da.target_square)
        groups.setdefault(key, []).append((4, "discovered_attacks", da))

    result: dict[str, list] = {
        "pins": [], "skewers": [], "xray_attacks": [], "discovered_attacks": [],
    }
    for entries in groups.values():
        entries.sort(key=lambda e: e[0])
        _, typ, obj = entries[0]
        result[typ].append(obj)

    return result


# ---------------------------------------------------------------------------
# MotifSpec and registry
# ---------------------------------------------------------------------------

@dataclass
class MotifSpec:
    """Declarative specification for a motif type.

    Maps a TacticalMotifs field to its diff key, key extractor,
    renderer, and optional cap. Ray-type motifs use ray_dedup_key
    for cached deduplication in render_motifs().
    """
    diff_key: str
    field: str
    key_fn: Callable[[Any], tuple]
    render_fn: Callable[[Any, RenderContext], tuple[str, bool]]
    ray_dedup_key: str | None = None  # key into _dedup_ray_motifs result
    cap: int | None = None
    is_observation: bool = False  # True for latent/structural motifs
    priority: int = 50
    squares_fn: Callable[[Any], frozenset[str]] | None = None


MOTIF_REGISTRY: dict[str, MotifSpec] = {
    "pin": MotifSpec(
        diff_key="pin", field="pins",
        key_fn=lambda t: ("pin", t.pinner_square, t.pinned_square),
        render_fn=render_pin,
        ray_dedup_key="pins",
        priority=25,
    ),
    "fork": MotifSpec(
        diff_key="fork", field="forks",
        key_fn=lambda t: ("fork", t.forking_square, tuple(sorted(t.targets))),
        render_fn=render_fork,
        priority=20,
        squares_fn=lambda f: frozenset(f.targets),
    ),
    "skewer": MotifSpec(
        diff_key="skewer", field="skewers",
        key_fn=lambda t: ("skewer", t.attacker_square, t.front_square, t.behind_square),
        render_fn=render_skewer,
        ray_dedup_key="skewers",
        priority=25,
    ),
    "hanging": MotifSpec(
        diff_key="hanging", field="hanging",
        key_fn=lambda t: ("hanging", t.square, t.piece),
        render_fn=render_hanging,
        priority=30,
        squares_fn=lambda h: frozenset({h.square}),
    ),
    "discovered": MotifSpec(
        diff_key="discovered", field="discovered_attacks",
        key_fn=lambda t: ("discovered", t.slider_square, t.target_square),
        render_fn=render_discovered_attack,
        ray_dedup_key="discovered_attacks",
        cap=3,
        is_observation=True,
        priority=40,
    ),
    "double_check": MotifSpec(
        diff_key="double_check", field="double_checks",
        key_fn=lambda t: ("double_check", tuple(sorted(t.checker_squares))),
        render_fn=render_double_check,
        priority=10,
    ),
    "trapped": MotifSpec(
        diff_key="trapped", field="trapped_pieces",
        key_fn=lambda t: ("trapped", t.square, t.piece),
        render_fn=render_trapped_piece,
        priority=30,
    ),
    "mate_pattern": MotifSpec(
        diff_key="mate_pattern", field="mate_patterns",
        key_fn=lambda t: ("mate_pattern", t.pattern),
        render_fn=lambda mp, ctx: (f"{mp.pattern.replace('_', ' ').capitalize()} mate.", True),
        priority=10,
    ),
    "mate_threat": MotifSpec(
        diff_key="mate_threat", field="mate_threats",
        key_fn=lambda t: ("mate_threat", t.mating_square, t.threatening_color),
        render_fn=render_mate_threat,
        priority=15,
    ),
    "back_rank": MotifSpec(
        diff_key="back_rank", field="back_rank_weaknesses",
        key_fn=lambda t: ("back_rank", t.weak_color, t.king_square),
        render_fn=render_back_rank_weakness,
        is_observation=True,
        priority=45,
    ),
    "xray": MotifSpec(
        diff_key="xray", field="xray_attacks",
        key_fn=lambda t: ("xray", t.slider_square, t.target_square),
        render_fn=render_xray_attack,
        ray_dedup_key="xray_attacks",
        cap=3,
        is_observation=True,
        priority=45,
    ),
    "exposed_king": MotifSpec(
        diff_key="exposed_king", field="exposed_kings",
        key_fn=lambda t: ("exposed_king", t.color, t.king_square),
        render_fn=render_exposed_king,
        is_observation=True,
        priority=50,
    ),
    "overloaded": MotifSpec(
        diff_key="overloaded", field="overloaded_pieces",
        key_fn=lambda t: ("overloaded", t.square, t.piece),
        render_fn=render_overloaded_piece,
        priority=35,
    ),
    "capturable_defender": MotifSpec(
        diff_key="capturable_defender", field="capturable_defenders",
        key_fn=lambda t: ("capturable_defender", t.defender_square),
        render_fn=render_capturable_defender,
        priority=35,
    ),
}


# Scoring sets for teachability ranking — validated against registry keys
HIGH_VALUE_KEYS: frozenset[str] = frozenset({"double_check", "trapped"})
MODERATE_VALUE_KEYS: frozenset[str] = frozenset({"xray", "exposed_king", "overloaded", "capturable_defender"})
assert HIGH_VALUE_KEYS <= MOTIF_REGISTRY.keys(), f"HIGH_VALUE_KEYS has unknown keys: {HIGH_VALUE_KEYS - MOTIF_REGISTRY.keys()}"
assert MODERATE_VALUE_KEYS <= MOTIF_REGISTRY.keys(), f"MODERATE_VALUE_KEYS has unknown keys: {MODERATE_VALUE_KEYS - MOTIF_REGISTRY.keys()}"


# ---------------------------------------------------------------------------
# Registry-driven utilities
# ---------------------------------------------------------------------------

def all_tactic_keys(tactics: TacticalMotifs) -> set[tuple]:
    """Get all tactic keys from a TacticalMotifs instance.

    Each key is a tuple starting with the diff_key, followed by
    motif-specific identifying values (squares, pieces).
    """
    keys: set[tuple] = set()
    for spec in MOTIF_REGISTRY.values():
        for item in getattr(tactics, spec.field, []):
            keys.add(spec.key_fn(item))
    return keys


def motif_labels(tactics: TacticalMotifs, board: chess.Board | None = None) -> set[str]:
    """Extract motif type labels from TacticalMotifs.

    Returns a set of string labels like "pin", "fork", "mate_smothered".
    """
    labels: set[str] = set()
    for spec in MOTIF_REGISTRY.values():
        items = getattr(tactics, spec.field, [])
        if items:
            # mate_patterns get per-pattern labels instead of generic key
            if spec.diff_key == "mate_pattern":
                for mp in items:
                    labels.add(f"mate_{mp.pattern}")
            else:
                labels.add(spec.diff_key)
    if board is not None and board.is_checkmate():
        labels.add("checkmate")
    return labels


def render_motifs(
    tactics: TacticalMotifs,
    new_types: set[str],
    ctx: RenderContext,
    max_items: int | None = None,
    *,
    new_keys: set[tuple] | None = None,
) -> tuple[list[RenderedMotif], list[RenderedMotif], list[RenderedMotif]]:
    """Render all new motifs, returning (opportunities, threats, observations).

    Items from specs with is_observation=True go to observations regardless
    of the opportunity/threat classification.

    Results within each bucket are sorted by priority (ascending = most
    important first). If max_items is set, each bucket is capped.

    Fork-implies-hanging dedup: hanging pieces on fork target squares
    are suppressed since the fork already implies the capture.

    When *new_keys* is provided, only motifs whose key (via spec.key_fn)
    is in *new_keys* are rendered.  This gives per-item precision instead
    of the coarser type-level gate via *new_types*.
    """
    opps: list[RenderedMotif] = []
    thrs: list[RenderedMotif] = []
    obs: list[RenderedMotif] = []

    # Collect fork target squares for fork-implies-hanging dedup
    fork_squares: set[str] = set()
    if "fork" in new_types:
        for fork in getattr(tactics, "forks", []):
            fork_squares.update(fork.targets)

    # Compute ray dedup once (shared by pin/skewer/xray/discovered filters)
    ray_dedup: dict[str, list] | None = None

    for spec in MOTIF_REGISTRY.values():
        if spec.diff_key not in new_types:
            continue
        if spec.ray_dedup_key:
            if ray_dedup is None:
                ray_dedup = _dedup_ray_motifs(tactics)
            items = ray_dedup[spec.ray_dedup_key]
            if spec.diff_key == "discovered":
                items = [da for da in items if _is_significant_discovery(da)]
        else:
            items = list(getattr(tactics, spec.field, []))
        if spec.cap:
            items = items[:spec.cap]
        for item in items:
            # Key-level filtering: skip items not in new_keys
            if new_keys is not None and spec.key_fn(item) not in new_keys:
                continue

            # Fork-implies-hanging dedup
            if spec.diff_key == "hanging" and fork_squares:
                if spec.squares_fn and spec.squares_fn(item) & fork_squares:
                    continue

            desc, is_opp = spec.render_fn(item, ctx)
            # Skip motifs that render to empty text (e.g., validated but invalid)
            if not desc or not desc.strip():
                continue
            target_sq = spec.squares_fn(item) if spec.squares_fn else frozenset()
            rm = RenderedMotif(
                text=desc, is_opportunity=is_opp,
                diff_key=spec.diff_key, priority=spec.priority,
                target_squares=target_sq,
            )
            if spec.is_observation:
                obs.append(rm)
            elif is_opp:
                opps.append(rm)
            else:
                thrs.append(rm)

    # Sort by priority (ascending = most important first)
    opps.sort(key=lambda r: r.priority)
    thrs.sort(key=lambda r: r.priority)
    obs.sort(key=lambda r: r.priority)

    # Apply max_items cap
    if max_items is not None:
        opps = opps[:max_items]
        thrs = thrs[:max_items]
        obs = obs[:max_items]

    return opps, thrs, obs
