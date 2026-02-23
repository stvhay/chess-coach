"""Description layer for coaching reports (Layer 2).

Converts game tree positions and tactical motifs into natural-language
descriptions. Two main entry points:

- describe_position(tree, node) -- What does this position look like?
- describe_changes(tree, node) -- What changed from the parent position?

Motif rendering is delegated to motifs.py via the MOTIF_REGISTRY.
Tactic diffing finds new/resolved motifs between parent and child.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from server.analysis import TacticalMotifs, summarize_position
from server.game_tree import GameNode, GameTree
from server.motifs import (
    RenderContext,
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
# Main description functions
# ---------------------------------------------------------------------------

def describe_position(tree: GameTree, node: GameNode) -> str:
    """Describe what this position looks like -- used for the Position section.

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
            is_threat=is_future,
        )
        opps, thrs = render_motifs(current_tactics, new_types, ctx)

        # Checkmate
        if chain_node.board.is_checkmate():
            # Who delivered checkmate? The side that just moved.
            mover_is_student = (not chain_node.board.turn == chess.WHITE) == student_is_white
            if mover_is_student:
                opps.append("checkmate")
            else:
                thrs.append("checkmate")

        # Apply threat wrapping for ply 1+ (future moves)
        if i == 0:
            all_opportunities.extend(opps)
            all_threats.extend(thrs)
        elif opps or thrs:
            # Derive move info from board state
            node_san = chain_node.san if chain_node.move and chain_node.parent else ""
            mover_is_white = not chain_node.board.turn  # who just played
            move_num = chain_node.parent.board.fullmove_number if chain_node.parent else 1
            numbered = f"{move_num}.{node_san}" if mover_is_white else f"{move_num}...{node_san}"
            threatener = "White" if mover_is_white else "Black"

            for desc in opps + thrs:
                wrapped = f"{threatener} threatens {numbered}, {desc}"
                if threatener == player_color:
                    all_opportunities.append(wrapped)
                else:
                    all_threats.append(wrapped)

        prev_tactics = current_tactics

    return all_opportunities, all_threats
