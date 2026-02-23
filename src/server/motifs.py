"""Motif registry for coaching descriptions.

Consolidates tactical motif rendering, keying, and labeling into a
declarative registry. Each motif type is one MotifSpec entry — adding
a new motif means adding one entry + one render function.

Used by descriptions.py (rendering and diffing) and game_tree.py (labeling).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import chess

from server.analysis import TacticalMotifs


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _colored(piece_char: str) -> str:
    """Add color prefix: 'N' -> 'White N', 'p' -> 'Black P'."""
    color = "White" if piece_char.isupper() else "Black"
    return f"{color} {piece_char.upper()}"


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


def _ray_direction(from_sq: str, to_sq: str) -> tuple[int, int]:
    """Normalized compass direction between two algebraic squares."""
    df = ord(to_sq[0]) - ord(from_sq[0])
    dr = int(to_sq[1]) - int(from_sq[1])
    return ((1 if df > 0 else -1) if df else 0,
            (1 if dr > 0 else -1) if dr else 0)


# ---------------------------------------------------------------------------
# Render context
# ---------------------------------------------------------------------------

@dataclass
class RenderContext:
    """Context for motif renderers."""
    student_is_white: bool | None
    player_color: str           # "White" or "Black"
    is_threat: bool = False     # True for ply 1+ annotations


# ---------------------------------------------------------------------------
# Motif renderers
# ---------------------------------------------------------------------------

def render_fork(fork, ctx: RenderContext) -> tuple[str, bool]:
    """Render a fork. Returns (description, is_opportunity)."""
    is_student = _piece_is_students(fork.forking_piece, ctx.student_is_white)
    if fork.target_pieces:
        target_descs = [
            f"{_colored(tp)} on {sq}"
            for tp, sq in zip(fork.target_pieces, fork.targets)
        ]
        targets = " and ".join(target_descs)
    else:
        targets = ", ".join(fork.targets)
    desc = (f"fork by {_colored(fork.forking_piece)} on {fork.forking_square} "
            f"targeting {targets}")
    if fork.target_pieces and any(tp.upper() == "K" for tp in fork.target_pieces):
        other = [f"{_colored(tp)}" for tp in fork.target_pieces if tp.upper() != "K"]
        if other:
            desc += f" (wins the {other[0]})"
    return desc, is_student


def render_pin(pin, ctx: RenderContext) -> tuple[str, bool]:
    """Render a pin. Returns (description, is_opportunity)."""
    is_student = _piece_is_students(pin.pinner_piece, ctx.student_is_white)
    abs_label = " (cannot move)" if pin.is_absolute else ""
    if pin.pinned_to_piece:
        to_desc = f"{_colored(pin.pinned_to_piece)} on {pin.pinned_to}"
    else:
        to_desc = pin.pinned_to
    desc = (f"pin: {_colored(pin.pinned_piece)} on {pin.pinned_square} pinned by "
            f"{_colored(pin.pinner_piece)} on {pin.pinner_square} to {to_desc}"
            f"{abs_label}")
    return desc, is_student


def render_skewer(skewer, ctx: RenderContext) -> tuple[str, bool]:
    """Render a skewer."""
    is_student = _piece_is_students(skewer.attacker_piece, ctx.student_is_white)
    desc = (f"skewer by {_colored(skewer.attacker_piece)} on {skewer.attacker_square}: "
            f"{_colored(skewer.front_piece)} on {skewer.front_square}, "
            f"{_colored(skewer.behind_piece)} on {skewer.behind_square}")
    return desc, is_student


def render_hanging(hp, ctx: RenderContext) -> tuple[str, bool]:
    """Render a hanging piece."""
    if hp.color:
        is_opponents = not _color_is_students(hp.color, ctx.player_color)
    else:
        is_opponents = not _piece_is_students(hp.piece, ctx.student_is_white)
    if hp.can_retreat:
        desc = f"{_colored(hp.piece)} on {hp.square} is undefended (must move)"
    else:
        desc = f"hanging {_colored(hp.piece)} on {hp.square}"
    return desc, is_opponents


def render_discovered_attack(da, ctx: RenderContext) -> tuple[str, bool]:
    """Render a discovered attack."""
    is_student = _piece_is_students(da.slider_piece, ctx.student_is_white)
    desc = (f"discovered attack: {_colored(da.blocker_piece)} on {da.blocker_square} "
            f"reveals {_colored(da.slider_piece)} on {da.slider_square} targeting "
            f"{_colored(da.target_piece)} on {da.target_square}")
    return desc, is_student


def render_double_check(dc, ctx: RenderContext) -> tuple[str, bool]:
    """Render a double check.

    Uses is_threat from ctx to determine opportunity: at ply 0
    the student delivered it (opportunity), at ply 1+ it's a threat.
    """
    squares = ", ".join(dc.checker_squares)
    desc = f"double check from {squares}"
    return desc, not ctx.is_threat


def render_trapped_piece(tp, ctx: RenderContext) -> tuple[str, bool]:
    """Render a trapped piece."""
    is_opponents = not _piece_is_students(tp.piece, ctx.student_is_white)
    desc = f"trapped {_colored(tp.piece)} on {tp.square}"
    return desc, is_opponents


def render_mate_threat(mt, ctx: RenderContext) -> tuple[str, bool]:
    """Render a mate threat."""
    is_student = _color_is_students(mt.threatening_color, ctx.player_color)
    desc = f"{mt.threatening_color} threatens checkmate on {mt.mating_square}"
    return desc, is_student


def render_back_rank_weakness(bw, ctx: RenderContext) -> tuple[str, bool]:
    """Render a back rank weakness."""
    is_opponents = not _color_is_students(bw.weak_color, ctx.player_color)
    desc = f"{bw.weak_color}'s back rank is weak (king on {bw.king_square})"
    return desc, is_opponents


def render_xray_attack(xa, ctx: RenderContext) -> tuple[str, bool]:
    """Render an x-ray attack."""
    is_student = _piece_is_students(xa.slider_piece, ctx.student_is_white)
    desc = (f"x-ray: {_colored(xa.slider_piece)} on {xa.slider_square} "
            f"through {_colored(xa.through_piece)} on {xa.through_square} "
            f"targeting {_colored(xa.target_piece)} on {xa.target_square}")
    return desc, is_student


def render_exposed_king(ek, ctx: RenderContext) -> tuple[str, bool]:
    """Render an exposed king."""
    is_opponents = not _color_is_students(ek.color, ctx.player_color)
    desc = f"{ek.color}'s king on {ek.king_square} is exposed (advanced, no pawn shield)"
    return desc, is_opponents


def render_overloaded_piece(op, ctx: RenderContext) -> tuple[str, bool]:
    """Render an overloaded piece."""
    is_opponents = not _piece_is_students(op.piece, ctx.student_is_white)
    charges = ", ".join(op.defended_squares)
    desc = (f"overloaded {_colored(op.piece)} on {op.square} "
            f"sole defender of {charges}")
    return desc, is_opponents


def render_capturable_defender(cd, ctx: RenderContext) -> tuple[str, bool]:
    """Render a capturable defender."""
    is_opponents = not _piece_is_students(cd.defender_piece, ctx.student_is_white)
    desc = (f"capturable defender: {_colored(cd.defender_piece)} on {cd.defender_square} "
            f"defends {_colored(cd.charge_piece)} on {cd.charge_square}")
    if cd.attacker_square:
        desc += (f" — if captured, {_colored(cd.charge_piece)} on "
                 f"{cd.charge_square} is left hanging")
    return desc, is_opponents


# ---------------------------------------------------------------------------
# Ray deduplication
# ---------------------------------------------------------------------------

def _dedup_ray_motifs(tactics: TacticalMotifs) -> dict[str, list]:
    """Remove geometric duplicates among pins, skewers, and x-rays.

    Groups by (attacker_square, normalized_direction) and keeps highest priority:
    absolute pin > non-absolute pin > skewer > x-ray.

    Returns dict with keys "pins", "skewers", "xray_attacks" -> filtered lists.
    """
    groups: dict[tuple[str, tuple[int, int]], list[tuple[int, str, object]]] = {}

    for pin in tactics.pins:
        direction = _ray_direction(pin.pinner_square, pin.pinned_square)
        key = (pin.pinner_square, direction)
        priority = 0 if pin.is_absolute else 1
        groups.setdefault(key, []).append((priority, "pins", pin))

    for skewer in tactics.skewers:
        direction = _ray_direction(skewer.attacker_square, skewer.front_square)
        key = (skewer.attacker_square, direction)
        groups.setdefault(key, []).append((2, "skewers", skewer))

    for xa in tactics.xray_attacks:
        direction = _ray_direction(xa.slider_square, xa.through_square)
        key = (xa.slider_square, direction)
        groups.setdefault(key, []).append((3, "xray_attacks", xa))

    result: dict[str, list] = {"pins": [], "skewers": [], "xray_attacks": []}
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
    renderer, optional filter, and optional cap.
    """
    diff_key: str
    field: str
    key_fn: Callable[[Any], tuple]
    render_fn: Callable[[Any, RenderContext], tuple[str, bool]]
    filter_fn: Callable[[list, TacticalMotifs], list] | None = None
    cap: int | None = None


def _pin_filter(items: list, tactics: TacticalMotifs) -> list:
    return _dedup_ray_motifs(tactics)["pins"]

def _skewer_filter(items: list, tactics: TacticalMotifs) -> list:
    return _dedup_ray_motifs(tactics)["skewers"]

def _xray_filter(items: list, tactics: TacticalMotifs) -> list:
    return _dedup_ray_motifs(tactics)["xray_attacks"]

def _discovered_filter(items: list, tactics: TacticalMotifs) -> list:
    return [da for da in items if _is_significant_discovery(da)]


MOTIF_REGISTRY: list[MotifSpec] = [
    MotifSpec(
        diff_key="pin", field="pins",
        key_fn=lambda t: ("pin", t.pinner_square, t.pinned_square),
        render_fn=render_pin,
        filter_fn=_pin_filter,
    ),
    MotifSpec(
        diff_key="fork", field="forks",
        key_fn=lambda t: ("fork", t.forking_square, tuple(sorted(t.targets))),
        render_fn=render_fork,
    ),
    MotifSpec(
        diff_key="skewer", field="skewers",
        key_fn=lambda t: ("skewer", t.attacker_square, t.front_square, t.behind_square),
        render_fn=render_skewer,
        filter_fn=_skewer_filter,
    ),
    MotifSpec(
        diff_key="hanging", field="hanging",
        key_fn=lambda t: ("hanging", t.square, t.piece),
        render_fn=render_hanging,
    ),
    MotifSpec(
        diff_key="discovered", field="discovered_attacks",
        key_fn=lambda t: ("discovered", t.slider_square, t.target_square),
        render_fn=render_discovered_attack,
        filter_fn=_discovered_filter,
        cap=3,
    ),
    MotifSpec(
        diff_key="double_check", field="double_checks",
        key_fn=lambda t: ("double_check", tuple(sorted(t.checker_squares))),
        render_fn=render_double_check,
    ),
    MotifSpec(
        diff_key="trapped", field="trapped_pieces",
        key_fn=lambda t: ("trapped", t.square, t.piece),
        render_fn=render_trapped_piece,
    ),
    MotifSpec(
        diff_key="mate_pattern", field="mate_patterns",
        key_fn=lambda t: ("mate_pattern", t.pattern),
        render_fn=lambda mp, ctx: (f"mate pattern: {mp.pattern}", True),
    ),
    MotifSpec(
        diff_key="mate_threat", field="mate_threats",
        key_fn=lambda t: ("mate_threat", t.mating_square, t.threatening_color),
        render_fn=render_mate_threat,
    ),
    MotifSpec(
        diff_key="back_rank", field="back_rank_weaknesses",
        key_fn=lambda t: ("back_rank", t.weak_color, t.king_square),
        render_fn=render_back_rank_weakness,
    ),
    MotifSpec(
        diff_key="xray", field="xray_attacks",
        key_fn=lambda t: ("xray", t.slider_square, t.target_square),
        render_fn=render_xray_attack,
        filter_fn=_xray_filter,
        cap=3,
    ),
    MotifSpec(
        diff_key="exposed_king", field="exposed_kings",
        key_fn=lambda t: ("exposed_king", t.color, t.king_square),
        render_fn=render_exposed_king,
    ),
    MotifSpec(
        diff_key="overloaded", field="overloaded_pieces",
        key_fn=lambda t: ("overloaded", t.square, t.piece),
        render_fn=render_overloaded_piece,
    ),
    MotifSpec(
        diff_key="capturable_defender", field="capturable_defenders",
        key_fn=lambda t: ("capturable_defender", t.defender_square),
        render_fn=render_capturable_defender,
    ),
]


# ---------------------------------------------------------------------------
# Registry-driven utilities
# ---------------------------------------------------------------------------

def all_tactic_keys(tactics: TacticalMotifs) -> set[tuple]:
    """Get all tactic keys from a TacticalMotifs instance.

    Each key is a tuple starting with the diff_key, followed by
    motif-specific identifying values (squares, pieces).
    """
    keys: set[tuple] = set()
    for spec in MOTIF_REGISTRY:
        for item in getattr(tactics, spec.field, []):
            keys.add(spec.key_fn(item))
    return keys


def motif_labels(tactics: TacticalMotifs, board: chess.Board | None = None) -> set[str]:
    """Extract motif type labels from TacticalMotifs.

    Returns a set of string labels like "pin", "fork", "mate_smothered".
    """
    labels: set[str] = set()
    for spec in MOTIF_REGISTRY:
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
) -> tuple[list[str], list[str]]:
    """Render all new motifs, returning (opportunities, threats).

    Replaces the 14-block if/elif dispatch in describe_changes.
    """
    opps: list[str] = []
    thrs: list[str] = []
    for spec in MOTIF_REGISTRY:
        if spec.diff_key not in new_types:
            continue
        items = list(getattr(tactics, spec.field, []))
        if spec.filter_fn:
            items = spec.filter_fn(items, tactics)
        if spec.cap:
            items = items[:spec.cap]
        for item in items:
            desc, is_opp = spec.render_fn(item, ctx)
            (opps if is_opp else thrs).append(desc)
    return opps, thrs
