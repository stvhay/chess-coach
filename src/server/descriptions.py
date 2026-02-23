"""Description layer for coaching reports (Layer 2).

Converts game tree positions and tactical motifs into natural-language
descriptions. Two main entry points:

- describe_position(tree, node) — What does this position look like?
- describe_changes(tree, node) — What changed from the parent position?

Motif renderers produce natural language for each tactic type.
Tactic diffing finds new/resolved motifs between parent and child.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from server.analysis import (
    TacticalMotifs,
    analyze,
    summarize_position,
)
from server.game_tree import GameNode, GameTree


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _colored(piece_char: str) -> str:
    """Add color prefix: 'N' → 'White N', 'p' → 'Black P'."""
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


def render_double_check(dc, ctx: RenderContext, ply: int) -> tuple[str, bool]:
    """Render a double check."""
    squares = ", ".join(dc.checker_squares)
    desc = f"double check from {squares}"
    return desc, ply % 2 == 0  # even plies = student's opportunity


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
# Geometric deduplication for ray-based motifs
# ---------------------------------------------------------------------------

def _deduplicate_line_motifs(tactics: TacticalMotifs):
    """Remove geometric duplicates among pins, skewers, and x-rays.

    Group by (attacker_square, normalized_direction) and keep highest priority:
    absolute pin > non-absolute pin > skewer > x-ray.

    Returns (keep_pins, keep_skewers, keep_xrays) — filtered lists.
    """
    groups: dict[tuple[str, tuple[int, int]], list[tuple[int, str, object]]] = {}

    for pin in tactics.pins:
        direction = _ray_direction(pin.pinner_square, pin.pinned_square)
        key = (pin.pinner_square, direction)
        priority = 0 if pin.is_absolute else 1
        groups.setdefault(key, []).append((priority, "pin", pin))

    for skewer in tactics.skewers:
        direction = _ray_direction(skewer.attacker_square, skewer.front_square)
        key = (skewer.attacker_square, direction)
        groups.setdefault(key, []).append((2, "skewer", skewer))

    for xa in tactics.xray_attacks:
        direction = _ray_direction(xa.slider_square, xa.through_square)
        key = (xa.slider_square, direction)
        groups.setdefault(key, []).append((3, "xray", xa))

    keep_pins = []
    keep_skewers = []
    keep_xrays = []
    for entries in groups.values():
        entries.sort(key=lambda e: e[0])
        _, typ, obj = entries[0]
        if typ == "pin":
            keep_pins.append(obj)
        elif typ == "skewer":
            keep_skewers.append(obj)
        else:
            keep_xrays.append(obj)

    return keep_pins, keep_skewers, keep_xrays


# ---------------------------------------------------------------------------
# Tactic diffing
# ---------------------------------------------------------------------------

def _tactic_key(tactic, tactic_type: str) -> tuple:
    """Create a comparable key for a tactic instance.

    Two tactics are "same" if same type + same key squares.
    """
    if tactic_type == "pin":
        return ("pin", tactic.pinner_square, tactic.pinned_square)
    if tactic_type == "fork":
        return ("fork", tactic.forking_square, tuple(sorted(tactic.targets)))
    if tactic_type == "skewer":
        return ("skewer", tactic.attacker_square, tactic.front_square, tactic.behind_square)
    if tactic_type == "hanging":
        return ("hanging", tactic.square, tactic.piece)
    if tactic_type == "discovered_attack":
        return ("discovered", tactic.slider_square, tactic.target_square)
    if tactic_type == "double_check":
        return ("double_check", tuple(sorted(tactic.checker_squares)))
    if tactic_type == "trapped":
        return ("trapped", tactic.square, tactic.piece)
    if tactic_type == "mate_pattern":
        return ("mate_pattern", tactic.pattern)
    if tactic_type == "mate_threat":
        return ("mate_threat", tactic.mating_square, tactic.threatening_color)
    if tactic_type == "back_rank":
        return ("back_rank", tactic.weak_color, tactic.king_square)
    if tactic_type == "xray":
        return ("xray", tactic.slider_square, tactic.target_square)
    if tactic_type == "exposed_king":
        return ("exposed_king", tactic.color, tactic.king_square)
    if tactic_type == "overloaded":
        return ("overloaded", tactic.square, tactic.piece)
    if tactic_type == "capturable_defender":
        return ("capturable_defender", tactic.defender_square)
    return (tactic_type, id(tactic))


def _all_tactic_keys(tactics: TacticalMotifs) -> set[tuple]:
    """Get all tactic keys from a TacticalMotifs instance."""
    keys: set[tuple] = set()
    for t in tactics.pins:
        keys.add(_tactic_key(t, "pin"))
    for t in tactics.forks:
        keys.add(_tactic_key(t, "fork"))
    for t in tactics.skewers:
        keys.add(_tactic_key(t, "skewer"))
    for t in tactics.hanging:
        keys.add(_tactic_key(t, "hanging"))
    for t in tactics.discovered_attacks:
        keys.add(_tactic_key(t, "discovered_attack"))
    for t in tactics.double_checks:
        keys.add(_tactic_key(t, "double_check"))
    for t in tactics.trapped_pieces:
        keys.add(_tactic_key(t, "trapped"))
    for t in tactics.mate_patterns:
        keys.add(_tactic_key(t, "mate_pattern"))
    for t in tactics.mate_threats:
        keys.add(_tactic_key(t, "mate_threat"))
    for t in tactics.back_rank_weaknesses:
        keys.add(_tactic_key(t, "back_rank"))
    for t in tactics.xray_attacks:
        keys.add(_tactic_key(t, "xray"))
    for t in tactics.exposed_kings:
        keys.add(_tactic_key(t, "exposed_king"))
    for t in tactics.overloaded_pieces:
        keys.add(_tactic_key(t, "overloaded"))
    for t in tactics.capturable_defenders:
        keys.add(_tactic_key(t, "capturable_defender"))
    return keys


@dataclass
class TacticDiff:
    """Result of comparing tactics between two positions."""
    new_keys: set[tuple]
    resolved_keys: set[tuple]
    persistent_keys: set[tuple]


def diff_tactics(parent_tactics: TacticalMotifs, child_tactics: TacticalMotifs) -> TacticDiff:
    """Compare tactics between parent and child positions.

    Returns new, resolved, and persistent tactic keys.
    """
    parent_keys = _all_tactic_keys(parent_tactics)
    child_keys = _all_tactic_keys(child_tactics)
    return TacticDiff(
        new_keys=child_keys - parent_keys,
        resolved_keys=parent_keys - child_keys,
        persistent_keys=parent_keys & child_keys,
    )


def _new_motif_types(diff: TacticDiff) -> set[str]:
    """Extract motif type labels from the new tactic keys in a diff."""
    types: set[str] = set()
    for key in diff.new_keys:
        types.add(key[0])
    return types


# ---------------------------------------------------------------------------
# Main description functions
# ---------------------------------------------------------------------------

def describe_position(tree: GameTree, node: GameNode) -> str:
    """Describe what this position looks like — used for the Position section.

    Uses summarize_position() from analysis.py for the core summary.
    """
    return summarize_position(node.report)


def describe_changes(
    tree: GameTree,
    node: GameNode,
    max_plies: int = 3,
) -> tuple[list[str], list[str]]:
    """Describe what changed from parent to this node.

    Returns (opportunities, threats) as lists of description strings.

    Walks into children for threat context, diffs tactics between
    parent and child to find new motifs.
    """
    if node.parent is None:
        return [], []

    player_color = "White" if tree.player_color == chess.WHITE else "Black"
    student_is_white = tree.player_color == chess.WHITE
    ctx = RenderContext(
        student_is_white=student_is_white,
        player_color=player_color,
    )

    all_opportunities: list[str] = []
    all_threats: list[str] = []

    # Walk the continuation chain (node itself + its children linearly)
    chain = [node]
    current = node
    for _ in range(max_plies - 1):
        if not current.children:
            break
        current = current.children[0]
        chain.append(current)

    # Compute fullmove number of the student's move (the node's parent context)
    fullmove = node.parent.board.fullmove_number

    prev_tactics = node.parent.tactics
    pv_san: list[str] = []

    for i, chain_node in enumerate(chain):
        current_tactics = chain_node.tactics
        diff = diff_tactics(prev_tactics, current_tactics)
        new_types = _new_motif_types(diff)

        if not new_types:
            prev_tactics = current_tactics
            if chain_node.move is not None and chain_node.parent is not None:
                pv_san.append(chain_node.san)
            continue

        # Collect the current node's SAN for threat wrapping
        if chain_node.move is not None and chain_node.parent is not None:
            node_san = chain_node.san
            pv_san.append(node_san)
        else:
            node_san = ""

        # Deduplicate ray-based motifs
        keep_pins, keep_skewers, keep_xrays = _deduplicate_line_motifs(current_tactics)
        keep_pin_set = set(id(p) for p in keep_pins)
        keep_skewer_set = set(id(s) for s in keep_skewers)
        keep_xray_set = set(id(x) for x in keep_xrays)

        opps: list[str] = []
        thrs: list[str] = []
        described: set[str] = set()

        # Render each new motif type
        if "fork" in new_types:
            for fork in current_tactics.forks:
                desc, is_opp = render_fork(fork, ctx)
                described.add("fork")
                (opps if is_opp else thrs).append(desc)

        if "pin" in new_types:
            described.add("pin")
            for pin in current_tactics.pins:
                if id(pin) not in keep_pin_set:
                    continue
                desc, is_opp = render_pin(pin, ctx)
                (opps if is_opp else thrs).append(desc)

        if "skewer" in new_types:
            described.add("skewer")
            for skewer in current_tactics.skewers:
                if id(skewer) not in keep_skewer_set:
                    continue
                desc, is_opp = render_skewer(skewer, ctx)
                (opps if is_opp else thrs).append(desc)

        if "hanging" in new_types:
            for hp in current_tactics.hanging:
                described.add("hanging")
                desc, is_opp = render_hanging(hp, ctx)
                (opps if is_opp else thrs).append(desc)

        if "discovered" in new_types:
            significant = [da for da in current_tactics.discovered_attacks
                           if _is_significant_discovery(da)]
            for da in significant[:3]:
                described.add("discovered")
                desc, is_opp = render_discovered_attack(da, ctx)
                (opps if is_opp else thrs).append(desc)

        if "double_check" in new_types:
            for dc in current_tactics.double_checks:
                described.add("double_check")
                desc, is_opp = render_double_check(dc, ctx, i)
                (opps if is_opp else thrs).append(desc)

        if "trapped" in new_types:
            for tp in current_tactics.trapped_pieces:
                described.add("trapped")
                desc, is_opp = render_trapped_piece(tp, ctx)
                (opps if is_opp else thrs).append(desc)

        if "mate_threat" in new_types:
            for mt in current_tactics.mate_threats:
                described.add("mate_threat")
                desc, is_opp = render_mate_threat(mt, ctx)
                (opps if is_opp else thrs).append(desc)

        if "back_rank" in new_types:
            for bw in current_tactics.back_rank_weaknesses:
                described.add("back_rank")
                desc, is_opp = render_back_rank_weakness(bw, ctx)
                (opps if is_opp else thrs).append(desc)

        if "xray" in new_types:
            described.add("xray")
            for xa in current_tactics.xray_attacks[:3]:
                if id(xa) not in keep_xray_set:
                    continue
                desc, is_opp = render_xray_attack(xa, ctx)
                (opps if is_opp else thrs).append(desc)

        if "exposed_king" in new_types:
            for ek in current_tactics.exposed_kings:
                described.add("exposed_king")
                desc, is_opp = render_exposed_king(ek, ctx)
                (opps if is_opp else thrs).append(desc)

        if "overloaded" in new_types:
            for op in current_tactics.overloaded_pieces:
                described.add("overloaded")
                desc, is_opp = render_overloaded_piece(op, ctx)
                (opps if is_opp else thrs).append(desc)

        if "capturable_defender" in new_types:
            for cd in current_tactics.capturable_defenders:
                described.add("capturable_defender")
                desc, is_opp = render_capturable_defender(cd, ctx)
                (opps if is_opp else thrs).append(desc)

        # Checkmate
        if chain_node.board.is_checkmate():
            if i % 2 == 0:
                opps.append("checkmate")
            else:
                thrs.append("checkmate")

        # Apply threat wrapping for ply 1+ (future moves)
        if i == 0:
            all_opportunities.extend(opps)
            all_threats.extend(thrs)
        else:
            # Determine who plays this ply and format the numbered move
            if student_is_white:
                ply_is_white = (i % 2 == 0)
            else:
                ply_is_white = (i % 2 == 1)

            if ply_is_white:
                move_num = fullmove + (i + 1) // 2 if student_is_white else fullmove + i // 2
                numbered = f"{move_num}.{node_san}"
            else:
                move_num = fullmove + i // 2 if student_is_white else fullmove + (i + 1) // 2
                numbered = f"{move_num}...{node_san}"

            threatener = "White" if ply_is_white else "Black"
            for desc in opps + thrs:
                wrapped = f"{threatener} threatens {numbered}, {desc}"
                if threatener == player_color:
                    all_opportunities.append(wrapped)
                else:
                    all_threats.append(wrapped)

        prev_tactics = current_tactics

    return all_opportunities, all_threats
