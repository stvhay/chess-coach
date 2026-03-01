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


def _detect_pin_hanging_chains(tactics: TacticalMotifs) -> dict[tuple, tuple]:
    """Detect pin->hanging chains from precomputed defense_notes. No board needed.

    Returns {pin_key: hanging_key} for each chain found.
    Only active when CHESS_TEACHER_ENABLE_CHAINING=1.
    """
    from server.config_flags import is_chain_detection_enabled
    if not is_chain_detection_enabled():
        return {}
    chains: dict[tuple, tuple] = {}
    for hanging in tactics.hanging:
        if not hanging.value or not hanging.value.defense_notes:
            continue
        notes = hanging.value.defense_notes.lower()
        for pin in tactics.pins:
            if pin.pinned_square.lower() in notes and "pinned" in notes:
                pin_key = ("pin", pin.pinner_square, pin.pinned_square, pin.pinned_to, pin.is_absolute)
                hanging_key = ("hanging", hanging.square, hanging.piece, hanging.color)
                chains[pin_key] = hanging_key
                break  # one pin per hanging piece for Tier 1
    return chains


def _detect_overload_hanging_chains(
    tactics: TacticalMotifs,
) -> dict[tuple, list[tuple]]:
    """Match OverloadedPiece.defended_squares against HangingPiece.square.

    Returns {overloaded_key: [hanging_key, ...]} for each chain found.
    An overloaded piece can link to multiple hanging pieces (it defends
    multiple squares, more than one may be hanging).

    Only active when is_tier2_chains_enabled().
    """
    from server.config_flags import is_tier2_chains_enabled
    if not is_tier2_chains_enabled():
        return {}

    # Build hanging lookup: square -> hanging key
    hanging_by_square: dict[str, tuple] = {}
    for h in tactics.hanging:
        h_key = ("hanging", h.square, h.piece, h.color)
        hanging_by_square[h.square] = h_key

    chains: dict[tuple, list[tuple]] = {}
    for op in tactics.overloaded_pieces:
        matched_hanging: list[tuple] = []
        for sq in op.defended_squares:
            if sq in hanging_by_square:
                matched_hanging.append(hanging_by_square[sq])
        if matched_hanging:
            op_key = ("overloaded", op.square, op.piece, tuple(sorted(op.defended_squares)))
            chains[op_key] = matched_hanging
    return chains


def _detect_capturable_defender_hanging_chains(
    tactics: TacticalMotifs,
) -> dict[tuple, tuple]:
    """Match CapturableDefender.charge_square against HangingPiece.square.

    Returns {cd_key: hanging_key} for each chain found.
    Only active when is_tier2_chains_enabled().
    """
    from server.config_flags import is_tier2_chains_enabled
    if not is_tier2_chains_enabled():
        return {}

    hanging_by_square: dict[str, tuple] = {}
    for h in tactics.hanging:
        h_key = ("hanging", h.square, h.piece, h.color)
        hanging_by_square[h.square] = h_key

    chains: dict[tuple, tuple] = {}
    for cd in tactics.capturable_defenders:
        if cd.charge_square in hanging_by_square:
            cd_key = ("capturable_defender", cd.defender_square, cd.charge_square)
            chains[cd_key] = hanging_by_square[cd.charge_square]
    return chains


def _render_chain_merged(pin, hanging, ctx: RenderContext) -> tuple[str, bool]:
    """Render pin->hanging chain as one merged description."""
    pin_text, pin_is_opp = render_pin(pin, ctx)
    # Build hanging piece reference
    if hanging.color:
        is_opp_h = not _color_is_students(hanging.color, ctx.player_color)
    else:
        is_opp_h = not _piece_is_students(hanging.piece, ctx.student_is_white)
    h_desc = _own_their(hanging.piece, not is_opp_h)
    # Strip trailing period and any value suffix, add chain clause
    base = pin_text.rstrip(".")
    chain_clause = f", leaving {h_desc} on {hanging.square} undefended"
    suffix = _value_suffix(hanging, ctx, is_opportunity=pin_is_opp)
    if suffix:
        chain_clause += suffix
    return base + chain_clause + ".", pin_is_opp


def _render_overload_chain_merged(
    op, hanging_squares: list[str], ctx: RenderContext,
) -> tuple[str, bool]:
    """Render overloaded piece with hanging consequence merged in."""
    is_opponents = not _piece_is_students(op.piece, ctx.student_is_white)
    piece_desc = _own_their(op.piece, not is_opponents)
    charges = ", ".join(op.defended_squares)

    if len(hanging_squares) == 1:
        consequence = f"{hanging_squares[0]} is hanging"
    else:
        consequence = f"{', '.join(hanging_squares[:-1])} and {hanging_squares[-1]} are hanging"

    desc = (f"{piece_desc.capitalize()} on {op.square} is overloaded, "
            f"sole defender of {charges} — {consequence}.")

    suffix = _value_suffix(op, ctx, is_opportunity=is_opponents)
    if suffix and desc.endswith("."):
        desc = desc[:-1] + suffix + "."
    return desc, is_opponents


# ---------------------------------------------------------------------------
# Render context
# ---------------------------------------------------------------------------


class RenderMode(enum.Enum):
    """How the motif is being rendered."""
    OPPORTUNITY = "opportunity"
    THREAT = "threat"
    POSITION = "position"


@dataclass
class RenderConfig:
    """Tunable configuration for value-aware motif rendering."""
    min_notable_value: int = 300      # mention value if material_delta >= this (centipawns)
    always_qualify_unsound: bool = True  # always explain why unsound tactics fail
    show_exact_cp: bool = True        # include centipawn numbers in text


@dataclass
class RenderContext:
    """Context for motif renderers."""
    student_is_white: bool | None
    player_color: str           # "White" or "Black"
    mode: RenderMode = RenderMode.OPPORTUNITY
    render_config: RenderConfig | None = None
    move_dest: str | None = None  # destination square of the move that created this position

    @property
    def is_threat(self) -> bool:
        return self.mode == RenderMode.THREAT

    @property
    def is_position_description(self) -> bool:
        return self.mode == RenderMode.POSITION


def _value_suffix(item, ctx: RenderContext, *, is_opportunity: bool = True) -> str:
    """Generate value text suffix for a tactic, or empty string.

    Only produces text for student opportunities. Threats (opponent tactics)
    are self-describing — the piece type conveys magnitude, and appending
    "wins ~Xcp" from the attacker's perspective would confuse the reader.
    """
    if not is_opportunity:
        return ""
    config = ctx.render_config
    if config is None:
        return ""
    value = getattr(item, "value", None)
    if value is None:
        return ""
    if value.is_sound and value.material_delta >= config.min_notable_value:
        if config.show_exact_cp:
            return f", wins ~{value.material_delta}cp in the exchange"
        return ", wins material in the exchange"
    if not value.is_sound and config.always_qualify_unsound:
        if config.show_exact_cp:
            return f", but loses ~{abs(value.material_delta)}cp in the exchange"
        return ", but loses material in the exchange"
    return ""


@dataclass
class RenderedMotif:
    """A rendered motif description with metadata."""
    text: str
    is_opportunity: bool
    diff_key: str
    priority: int
    target_squares: frozenset[str] = frozenset()
    material_delta: int | None = None  # from TacticValue, for threshold filtering


# ---------------------------------------------------------------------------
# Motif renderers
# ---------------------------------------------------------------------------

def _is_self_inflicted_fork(fork, ctx: RenderContext) -> str | None:
    """Detect if a fork was caused by the victim moving into the forker's range.

    Returns the destination square if self-inflicted, None otherwise.
    A fork is self-inflicted when:
      - we know the move that created this position (ctx.move_dest)
      - the forking piece did NOT just move (it was already there)
      - the move destination IS one of the fork targets (victim walked into range)
    """
    if ctx.move_dest is None:
        return None
    if fork.forking_square == ctx.move_dest:
        return None  # forker just moved here — genuine active fork
    if ctx.move_dest in fork.targets:
        return ctx.move_dest
    return None


def render_fork(fork, ctx: RenderContext) -> tuple[str, bool]:
    """Render a fork. Returns (description, is_opportunity).

    Pin-forks get different language: "pins X while also attacking Y"
    instead of "forks X and Y", since the pin is the primary motif.

    Self-inflicted forks (victim moved into forker's range) use
    "becomes another target for" instead of "forks".
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

    # Self-inflicted fork: the victim moved a piece into the forker's range
    self_inflicted_sq = _is_self_inflicted_fork(fork, ctx)
    if self_inflicted_sq and fork.target_pieces:
        # Find the piece that just moved into the fork
        arrived_idx = fork.targets.index(self_inflicted_sq)
        arrived_piece = fork.target_pieces[arrived_idx]
        arrived = _own_their(arrived_piece, _piece_is_students(arrived_piece, ctx.student_is_white))
        desc = f"{arrived.capitalize()} on {self_inflicted_sq} becomes another target for {forker} on {fork.forking_square}."
    elif fork.is_pin_fork:
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
    # Append value suffix before final period
    suffix = _value_suffix(fork, ctx, is_opportunity=is_student)
    if suffix and desc.endswith("."):
        desc = desc[:-1] + suffix + "."
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
    # Append value suffix before final period
    suffix = _value_suffix(pin, ctx, is_opportunity=is_student)
    if suffix and desc.endswith("."):
        desc = desc[:-1] + suffix + "."
    return desc, is_student


def _is_self_inflicted_skewer(skewer, ctx: RenderContext) -> bool:
    """Detect if a skewer was caused by the front piece moving into the attacker's line.

    Returns True when the front piece (the one that must move) just arrived
    on the skewer line — i.e. the victim walked into it.
    """
    if ctx.move_dest is None:
        return False
    if skewer.attacker_square == ctx.move_dest:
        return False  # attacker just moved here — genuine active skewer
    return ctx.move_dest == skewer.front_square


def render_skewer(skewer, ctx: RenderContext) -> tuple[str, bool]:
    """Render a skewer.

    Self-inflicted skewers (front piece moved into attacker's line) use
    "moved into a skewer" instead of crediting the attacker.
    """
    is_student = _piece_is_students(skewer.attacker_piece, ctx.student_is_white)
    attacker = _own_their(skewer.attacker_piece, is_student)
    front = _own_their(skewer.front_piece, _piece_is_students(skewer.front_piece, ctx.student_is_white))
    behind = _own_their(skewer.behind_piece, _piece_is_students(skewer.behind_piece, ctx.student_is_white))
    if _is_self_inflicted_skewer(skewer, ctx):
        desc = (f"{front.capitalize()} on {skewer.front_square} moved into a skewer "
                f"by {attacker} on {skewer.attacker_square}.")
    else:
        desc = (f"{attacker.capitalize()} on {skewer.attacker_square} skewers "
                f"{front} on {skewer.front_square} behind "
                f"{behind} on {skewer.behind_square}.")
    # Append value suffix before final period
    suffix = _value_suffix(skewer, ctx, is_opportunity=is_student)
    if suffix and desc.endswith("."):
        desc = desc[:-1] + suffix + "."
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
    # Append value suffix before final period
    suffix = _value_suffix(hp, ctx, is_opportunity=is_opponents)
    if suffix and desc.endswith("."):
        desc = desc[:-1] + suffix + "."
    return desc, is_opponents


def render_discovered_attack(da, ctx: RenderContext) -> tuple[str, bool]:
    """Render a discovered attack.

    In position context uses "x-ray alignment" since nothing has been
    "discovered" yet. In change context uses conditional tense — the
    blocker hasn't moved, so the attack is latent/potential.
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
        desc = (f"If {blocker} on {da.blocker_square} moves, "
                f"{slider} on {da.slider_square} will target "
                f"{target} on {da.target_square}.")
    # Append value suffix before final period
    suffix = _value_suffix(da, ctx, is_opportunity=is_student)
    if suffix and desc.endswith("."):
        desc = desc[:-1] + suffix + "."
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
    # Append value suffix before final period
    suffix = _value_suffix(op, ctx, is_opportunity=is_opponents)
    if suffix and desc.endswith("."):
        desc = desc[:-1] + suffix + "."
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
    # Append value suffix before final period
    suffix = _value_suffix(cd, ctx, is_opportunity=is_opponents)
    if suffix and desc.endswith("."):
        desc = desc[:-1] + suffix + "."
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
        key_fn=lambda t: ("pin", t.pinner_square, t.pinned_square, t.pinned_to, t.is_absolute),
        render_fn=render_pin,
        ray_dedup_key="pins",
        priority=25,
    ),
    "fork": MotifSpec(
        diff_key="fork", field="forks",
        key_fn=lambda t: ("fork", t.forking_square, tuple(sorted(zip(t.targets, t.target_pieces) if t.target_pieces else ((sq,) for sq in t.targets)))),
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
        key_fn=lambda t: ("hanging", t.square, t.piece, t.color),
        render_fn=render_hanging,
        priority=30,
        squares_fn=lambda h: frozenset({h.square}),
    ),
    "discovered": MotifSpec(
        diff_key="discovered", field="discovered_attacks",
        key_fn=lambda t: ("discovered", t.slider_square, t.target_square, t.blocker_square),
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
        key_fn=lambda t: ("overloaded", t.square, t.piece, tuple(sorted(t.defended_squares))),
        render_fn=render_overloaded_piece,
        priority=35,
    ),
    "capturable_defender": MotifSpec(
        diff_key="capturable_defender", field="capturable_defenders",
        key_fn=lambda t: ("capturable_defender", t.defender_square, t.charge_square),
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


def _apply_value_filter(
    bucket: list[RenderedMotif],
    min_value: int,
    guarantee_min: int,
) -> None:
    """Filter bucket in-place: remove valued items below min_value, keep guarantee_min."""
    if not bucket:
        return
    passing = [rm for rm in bucket if rm.material_delta is None or rm.material_delta >= min_value]
    failing = [rm for rm in bucket if rm.material_delta is not None and rm.material_delta < min_value]
    if len(passing) < guarantee_min and failing:
        failing.sort(key=lambda rm: rm.material_delta or 0, reverse=True)
        needed = guarantee_min - len(passing)
        passing.extend(failing[:needed])
    bucket[:] = sorted(passing, key=lambda r: r.priority)


def render_motifs(
    tactics: TacticalMotifs,
    new_types: set[str],
    ctx: RenderContext,
    max_items: int | None = None,
    *,
    new_keys: set[tuple] | None = None,
    min_value: int = 0,
    guarantee_min: int = 1,
    suppress_unsound_opps: bool = False,
) -> tuple[list[RenderedMotif], list[RenderedMotif], list[RenderedMotif], set[tuple]]:
    """Render all new motifs, returning (opportunities, threats, observations, rendered_keys).

    Items from specs with is_observation=True go to observations regardless
    of the opportunity/threat classification.

    Results within each bucket are sorted by priority (ascending = most
    important first). If max_items is set, each bucket is capped.

    Fork-implies-hanging dedup: hanging pieces on fork target squares
    are suppressed since the fork already implies the capture.

    When *new_keys* is provided, only motifs whose key (via spec.key_fn)
    is in *new_keys* are rendered.  This gives per-item precision instead
    of the coarser type-level gate via *new_types*.

    The fourth return value, *rendered_keys*, contains the key_fn tuple
    for every motif that was actually rendered (non-empty text, not
    filtered out). This allows callers to track exactly which motifs
    were shown, rather than inferring from the full tactic set.

    When *min_value* > 0, valued motifs below the threshold are filtered
    out (at the render layer only). *guarantee_min* ensures at least N
    items survive per bucket even if all are below threshold.
    """
    opps: list[RenderedMotif] = []
    thrs: list[RenderedMotif] = []
    obs: list[RenderedMotif] = []
    rendered_keys: set[tuple] = set()
    rm_to_key: dict[int, tuple] = {}  # id(RenderedMotif) -> key_fn tuple

    # Collect fork target squares for fork-implies-hanging dedup
    fork_squares: set[str] = set()
    if "fork" in new_types:
        for fork in getattr(tactics, "forks", []):
            fork_squares.update(fork.targets)

    # Chain detection (Tier 1: pin -> hanging)
    chains = _detect_pin_hanging_chains(tactics)
    hanging_in_chain: set[tuple] = set(chains.values())
    pin_in_chain: dict[tuple, tuple] = {pk: hk for pk, hk in chains.items()}

    # Chain detection (Tier 2: overload -> hanging, capturable_defender -> hanging)
    overload_chains = _detect_overload_hanging_chains(tactics)
    cd_chains = _detect_capturable_defender_hanging_chains(tactics)
    for h_keys in overload_chains.values():
        hanging_in_chain.update(h_keys)
    hanging_in_chain.update(cd_chains.values())
    # Track overloaded keys that need merged rendering
    overloaded_in_chain: dict[tuple, list[str]] = {}
    for op_key, h_keys in overload_chains.items():
        overloaded_in_chain[op_key] = [hk[1] for hk in h_keys]  # hk[1] is the square

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

            # Chain suppression: skip hanging pieces already merged into a pin chain
            if spec.diff_key == "hanging":
                h_key = spec.key_fn(item)
                if h_key in hanging_in_chain:
                    rendered_keys.add(h_key)  # track as rendered to prevent re-emergence
                    continue

            desc, is_opp = spec.render_fn(item, ctx)

            # Chain merge: replace pin description with merged pin+hanging narrative
            if spec.diff_key == "pin":
                p_key = spec.key_fn(item)
                if p_key in pin_in_chain:
                    h_key = pin_in_chain[p_key]
                    match = next(
                        (h for h in tactics.hanging
                         if ("hanging", h.square, h.piece, h.color) == h_key),
                        None,
                    )
                    if match is not None:
                        desc, is_opp = _render_chain_merged(item, match, ctx)
                        rendered_keys.add(h_key)  # mark hanging as rendered

            # Chain merge: replace overloaded description with merged overload+hanging
            if spec.diff_key == "overloaded":
                o_key = spec.key_fn(item)
                if o_key in overloaded_in_chain:
                    hanging_sqs = overloaded_in_chain[o_key]
                    desc, is_opp = _render_overload_chain_merged(
                        item, hanging_sqs, ctx,
                    )
                    for h_key in overload_chains[o_key]:
                        rendered_keys.add(h_key)

            # Skip motifs that render to empty text (e.g., validated but invalid)
            if not desc or not desc.strip():
                continue
            target_sq = spec.squares_fn(item) if spec.squares_fn else frozenset()
            item_value = getattr(item, "value", None)
            rm = RenderedMotif(
                text=desc, is_opportunity=is_opp,
                diff_key=spec.diff_key, priority=spec.priority,
                target_squares=target_sq,
                material_delta=item_value.material_delta if item_value else None,
            )
            if spec.is_observation:
                obs.append(rm)
            elif is_opp:
                # Suppress unsound opportunity motifs (e.g. fork that loses 800cp)
                # unless this is the actually-played move
                if suppress_unsound_opps and item_value and not item_value.is_sound:
                    continue
                opps.append(rm)
            else:
                thrs.append(rm)
            rendered_keys.add(spec.key_fn(item))
            rm_to_key[id(rm)] = spec.key_fn(item)

    # Sort by priority (ascending = most important first)
    opps.sort(key=lambda r: r.priority)
    thrs.sort(key=lambda r: r.priority)
    obs.sort(key=lambda r: r.priority)

    # Apply value threshold filter
    if min_value > 0:
        _apply_value_filter(opps, min_value, guarantee_min)
        _apply_value_filter(thrs, min_value, guarantee_min)
        _apply_value_filter(obs, min_value, guarantee_min)
        # Rebuild rendered_keys from survivors
        surviving_ids = {id(rm) for rm in opps + thrs + obs}
        rendered_keys = {k for rm_id, k in rm_to_key.items() if rm_id in surviving_ids}

    # Apply max_items cap
    if max_items is not None:
        opps = opps[:max_items]
        thrs = thrs[:max_items]
        obs = obs[:max_items]

    return opps, thrs, obs, rendered_keys
