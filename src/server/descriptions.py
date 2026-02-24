"""Description layer for coaching reports (Layer 2).

Converts game tree positions and tactical motifs into natural-language
descriptions. Two main entry points:

- describe_position(tree, node) -- What does this position look like?
- describe_changes(tree, node) -- What changed from the parent position?

Motif rendering is delegated to motifs.py via the MOTIF_REGISTRY.
Tactic diffing finds new/resolved motifs between parent and child.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from server.analysis import PositionReport, TacticalMotifs
from server.game_tree import GameNode, GameTree, _get_continuation_chain
from server.motifs import (
    MOTIF_REGISTRY,
    RenderContext,
    RenderMode,
    all_tactic_keys,
    render_motifs,
)


# ---------------------------------------------------------------------------
# Tactic diffing
# ---------------------------------------------------------------------------

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
    parent_keys = all_tactic_keys(parent_tactics)
    child_keys = all_tactic_keys(child_tactics)
    return TacticDiff(
        new_keys=child_keys - parent_keys,
        resolved_keys=parent_keys - child_keys,
        persistent_keys=parent_keys & child_keys,
    )


def _new_motif_types(diff: TacticDiff) -> set[str]:
    """Extract motif type labels from the new tactic keys in a diff."""
    return {key[0] for key in diff.new_keys}


# ---------------------------------------------------------------------------
# Position description
# ---------------------------------------------------------------------------

@dataclass
class PositionDescription:
    """Structured position description with three buckets."""
    threats: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)

    def as_text(self, max_items: int = 8) -> str:
        """Flatten to a single text string (for LLM context)."""
        parts = self.threats + self.opportunities + self.observations
        if not parts:
            return "The position is roughly balanced with no major imbalances."
        return " ".join(parts[:max_items])


def _should_skip_back_rank(report: PositionReport) -> bool:
    """Skip back rank weakness if both sides uncastled and fullmove < 10."""
    if report.fullmove_number >= 10:
        return False
    board = chess.Board(report.fen)
    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)
    if wk is None or bk is None:
        return False
    return chess.square_name(wk) == "e1" and chess.square_name(bk) == "e8"


def _add_positional_observations(report: PositionReport) -> list[str]:
    """Non-tactic positional observations for the position section."""
    parts: list[str] = []

    # Check / checkmate status
    if report.is_checkmate:
        parts.append("Checkmate.")
    elif report.is_check:
        side_in_check = report.turn.capitalize()
        parts.append(f"{side_in_check} is in check.")

    # Material imbalance
    mat = report.material
    if mat.imbalance > 0:
        parts.append(f"White is up approximately {mat.imbalance} points of material.")
    elif mat.imbalance < 0:
        parts.append(f"Black is up approximately {-mat.imbalance} points of material.")

    # Pawn structure
    ps = report.pawn_structure
    w_isolated = [p.square for p in ps.white if p.is_isolated]
    b_isolated = [p.square for p in ps.black if p.is_isolated]
    if w_isolated:
        parts.append(f"White has isolated pawns on {', '.join(w_isolated)}.")
    if b_isolated:
        parts.append(f"Black has isolated pawns on {', '.join(b_isolated)}.")

    w_passed = [p.square for p in ps.white if p.is_passed]
    b_passed = [p.square for p in ps.black if p.is_passed]
    if w_passed:
        parts.append(f"White has passed pawns on {', '.join(w_passed)}.")
    if b_passed:
        parts.append(f"Black has passed pawns on {', '.join(b_passed)}.")

    # King safety
    for color, ks in [("White", report.king_safety_white), ("Black", report.king_safety_black)]:
        if ks.open_files_near_king:
            parts.append(f"{color}'s king has open files nearby.")

    # Development
    dev = report.development
    if report.fullmove_number <= 15:
        if dev.white_developed < 3:
            parts.append("White has not fully developed minor pieces.")
        if dev.black_developed < 3:
            parts.append("Black has not fully developed minor pieces.")

    return parts


def describe_position_from_report(
    report: PositionReport,
    student_is_white: bool,
) -> PositionDescription:
    """Position description from a raw report — no GameTree needed."""
    player_color = "White" if student_is_white else "Black"
    tactics = report.tactics

    # Render all active motifs (use all types as "new" since this is a snapshot)
    all_types = {spec.diff_key for spec in MOTIF_REGISTRY.values()
                 if getattr(tactics, spec.field, [])}
    ctx = RenderContext(
        student_is_white=student_is_white,
        player_color=player_color,
        mode=RenderMode.POSITION,
    )
    opps_rm, thrs_rm, obs_rm = render_motifs(tactics, all_types, ctx)

    # Post-filter: skip back rank in early game
    skip_back_rank = _should_skip_back_rank(report)
    if skip_back_rank:
        obs_rm = [o for o in obs_rm if "back rank" not in o.text.lower()]

    # Extract text
    obs_text = [o.text for o in obs_rm]
    obs_text.extend(_add_positional_observations(report))

    return PositionDescription(
        threats=[t.text for t in thrs_rm],
        opportunities=[o.text for o in opps_rm],
        observations=obs_text,
    )


def describe_position(tree: GameTree, node: GameNode) -> PositionDescription:
    """Describe what this position looks like -- used for the Position section.

    Renders ALL active motifs via the registry and categorizes into three
    buckets. Adds non-tactic observations to the observations list.
    """
    student_is_white = tree.player_color == chess.WHITE
    return describe_position_from_report(node.report, student_is_white)


# ---------------------------------------------------------------------------
# Change descriptions
# ---------------------------------------------------------------------------

def describe_changes(
    tree: GameTree,
    node: GameNode,
    max_plies: int = 3,
) -> tuple[list[str], list[str], list[str]]:
    """Describe what changed from parent to this node.

    Returns (opportunities, threats, observations) as lists of description strings.

    Walks into children for threat context, diffs tactics between
    parent and child to find new motifs.
    """
    if node.parent is None:
        return [], [], []

    player_color = "White" if tree.player_color == chess.WHITE else "Black"
    student_is_white = tree.player_color == chess.WHITE

    all_opportunities: list[str] = []
    all_threats: list[str] = []
    all_observations: list[str] = []

    # Walk the continuation chain (node itself + up to max_plies-1 children)
    chain = _get_continuation_chain(node, max_depth=max_plies - 1)

    prev_tactics = node.parent.tactics

    for i, chain_node in enumerate(chain):
        current_tactics = chain_node.tactics
        diff = diff_tactics(prev_tactics, current_tactics)
        new_types = _new_motif_types(diff)

        # Render motifs via registry
        is_future = i > 0
        ctx = RenderContext(
            student_is_white=student_is_white,
            player_color=player_color,
            mode=RenderMode.THREAT if is_future else RenderMode.OPPORTUNITY,
        )
        opps_rm, thrs_rm, obs_rm = render_motifs(current_tactics, new_types, ctx)

        # Extract text lists for this ply
        opp_texts = [r.text for r in opps_rm]
        thr_texts = [r.text for r in thrs_rm]

        # Checkmate
        if chain_node.board.is_checkmate():
            # Who delivered checkmate? The side that just moved.
            mover_is_student = (not chain_node.board.turn == chess.WHITE) == student_is_white
            if mover_is_student:
                opp_texts.append("checkmate")
            else:
                thr_texts.append("checkmate")

        # Apply threat wrapping for ply 1+ (future moves)
        if i == 0:
            all_opportunities.extend(opp_texts)
            all_threats.extend(thr_texts)
        elif opp_texts or thr_texts:
            # Derive move info from board state
            node_san = chain_node.san if chain_node.move and chain_node.parent else ""
            mover_is_white = not chain_node.board.turn  # who just played
            move_num = chain_node.parent.board.fullmove_number if chain_node.parent else 1
            numbered = f"{move_num}.{node_san}" if mover_is_white else f"{move_num}...{node_san}"
            threatener = "White" if mover_is_white else "Black"

            for desc in opp_texts + thr_texts:
                wrapped = f"{threatener} threatens {numbered}, {desc}"
                if threatener == player_color:
                    all_opportunities.append(wrapped)
                else:
                    all_threats.append(wrapped)

        # Observations always added directly (structural, not threats)
        all_observations.extend(r.text for r in obs_rm)

        prev_tactics = current_tactics

    return all_opportunities, all_threats, all_observations
