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

import re

from server.analysis import PositionReport, TacticalMotifs
from server.game_tree import GameNode, GameTree, _get_continuation_chain
from server.motifs import (
    MOTIF_REGISTRY,
    RenderConfig,
    RenderContext,
    RenderMode,
    all_tactic_keys,
    render_motifs,
)


# ---------------------------------------------------------------------------
# Tense conversion — present to past
# ---------------------------------------------------------------------------

# Ordered list of (pattern, replacement). Applied in order; first match wins
# for each region of text. Patterns use word boundaries to avoid partial matches.
_PRESENT_TO_PAST: list[tuple[re.Pattern, str]] = [
    # --- Be-verbs (most common in motif output) ---
    (re.compile(r"\bare connected\b"), "were connected"),
    (re.compile(r"\bis left hanging\b"), "was left hanging"),
    (re.compile(r"\bis actively placed\b"), "was actively placed"),
    (re.compile(r"\bis in check\b"), "was in check"),
    (re.compile(r"\bis up approximately\b"), "was up approximately"),
    (re.compile(r"\bis undefended\b"), "was undefended"),
    (re.compile(r"\bis hanging\b"), "was hanging"),
    (re.compile(r"\bis trapped\b"), "was trapped"),
    (re.compile(r"\bis weak\b"), "was weak"),
    (re.compile(r"\bis exposed\b"), "was exposed"),
    (re.compile(r"\bis overloaded\b"), "was overloaded"),

    # --- Action verbs (motif renderers) ---
    (re.compile(r"\bpins and also attacks\b"), "pinned and also attacked"),
    (re.compile(r"\bforks\b"), "forked"),
    (re.compile(r"\bpins\b"), "pinned"),
    (re.compile(r"\bskewers\b"), "skewered"),
    (re.compile(r"\bx-rays\b"), "x-rayed"),
    (re.compile(r"\breveals\b"), "revealed"),
    (re.compile(r"\bthreaten\b"), "threatened"),
    (re.compile(r"\bdefends\b"), "defended"),
    (re.compile(r"\bcontrols\b"), "controlled"),
    (re.compile(r"\boccupies\b"), "occupied"),

    # --- Positional observations ---
    (re.compile(r"\bhas not fully developed\b"), "had not fully developed"),
    (re.compile(r"\bhas a weak\b"), "had a weak"),
    (re.compile(r"\bhas isolated\b"), "had isolated"),
    (re.compile(r"\bhas passed\b"), "had passed"),
    (re.compile(r"\bhas open files\b"), "had open files"),
]


def _to_past_tense(text: str) -> str:
    """Convert known present-tense verb forms to past tense.

    Uses an ordered list of regex substitutions. Each pattern matches at most
    once per sentence (re.sub replaces all occurrences, but our patterns are
    specific enough that double-matching is not a concern).

    Unrecognized verb forms pass through unchanged — this is intentional.
    New motif renderers should add their verb pattern here.
    """
    for pattern, replacement in _PRESENT_TO_PAST:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Board state validation
# ---------------------------------------------------------------------------

def _validate_motif_text(motif_text: str, board: chess.Board) -> bool:
    """Validate that a motif description's referenced squares exist on the board.

    Checks square names mentioned in the text (like 'c4', 'e6') to ensure they're
    not describing pieces/positions that don't match the board state. This prevents
    motif hallucination when rendering alternative lines.

    Returns True if the motif appears valid for this board, False if it references
    non-existent pieces or appears inconsistent.
    """
    # Extract square names from the text (all 2-letter combos matching square format)
    import re
    square_pattern = r'\b([a-h][1-8])\b'
    mentioned_squares = re.findall(square_pattern, motif_text.lower())

    if not mentioned_squares:
        # No squares mentioned, can't validate (allow it)
        return True

    # At least one mentioned square must have a piece on the board
    # (otherwise it's describing an empty square)
    for sq_name in mentioned_squares:
        try:
            sq = chess.parse_square(sq_name)
            if board.piece_at(sq) is not None:
                # Found a piece - motif references real board state
                return True
        except (ValueError, IndexError):
            continue

    # All mentioned squares are empty - likely hallucination
    return False


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

    is_endgame = report.phase == "endgame"

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
        suffix = " — critical in this endgame" if is_endgame else ""
        parts.append(f"White has passed pawns on {', '.join(w_passed)}{suffix}.")
    if b_passed:
        suffix = " — critical in this endgame" if is_endgame else ""
        parts.append(f"Black has passed pawns on {', '.join(b_passed)}{suffix}.")

    # King safety (in endgame, emphasize king activity instead)
    if is_endgame:
        for color, ks in [("White", report.king_safety_white), ("Black", report.king_safety_black)]:
            if ks.king_square:
                kr = int(ks.king_square[1])
                is_white = color == "White"
                # King is active if advanced past rank 3 (white) or rank 6 (black)
                if (is_white and kr >= 4) or (not is_white and kr <= 5):
                    parts.append(f"{color}'s king is actively placed on {ks.king_square}.")
    else:
        for color, ks in [("White", report.king_safety_white), ("Black", report.king_safety_black)]:
            if ks.open_files_near_king:
                parts.append(f"{color}'s king has open files nearby.")

    # Development (skip in endgame — irrelevant)
    if not is_endgame:
        dev = report.development
        if report.fullmove_number <= 15:
            if dev.white_developed < 3:
                parts.append("White has not fully developed minor pieces.")
            if dev.black_developed < 3:
                parts.append("Black has not fully developed minor pieces.")

    # File control and rook placement
    fd = report.files_and_diagonals
    if fd.rooks_on_seventh:
        for sq in fd.rooks_on_seventh:
            parts.append(f"Rook on {sq} occupies the 7th rank.")

    for pair in fd.connected_rooks_white:
        parts.append(f"White's rooks are connected on {pair}.")
    for pair in fd.connected_rooks_black:
        parts.append(f"Black's rooks are connected on {pair}.")

    # Long diagonal control
    for diag in fd.long_diagonals:
        if diag.bishop_square and diag.mobility >= 4 and not diag.is_blocked:
            parts.append(
                f"{diag.bishop_color.capitalize()}'s bishop on {diag.bishop_square} "
                f"controls the {diag.name} diagonal."
            )

    # Pawn color complex weakness
    pcc = fd.pawn_color_complex
    if pcc:
        if pcc.white_weak_color:
            parts.append(
                f"White has a weak {pcc.white_weak_color}-square complex "
                f"(no {pcc.white_weak_color}-squared bishop, "
                f"pawns on {'light' if pcc.white_weak_color == 'dark' else 'dark'} squares)."
            )
        if pcc.black_weak_color:
            parts.append(
                f"Black has a weak {pcc.black_weak_color}-square complex "
                f"(no {pcc.black_weak_color}-squared bishop, "
                f"pawns on {'light' if pcc.black_weak_color == 'dark' else 'dark'} squares)."
            )

    return parts


def describe_position_from_report(
    report: PositionReport,
    student_is_white: bool,
    *,
    tense: str = "present",
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
        render_config=RenderConfig(),
    )
    opps_rm, thrs_rm, obs_rm, _ = render_motifs(tactics, all_types, ctx)

    # Post-filter: skip back rank in early game
    skip_back_rank = _should_skip_back_rank(report)
    if skip_back_rank:
        obs_rm = [o for o in obs_rm if "back rank" not in o.text.lower()]

    # Extract text
    obs_text = [o.text for o in obs_rm]
    obs_text.extend(_add_positional_observations(report))

    if tense == "past":
        convert = _to_past_tense
        return PositionDescription(
            threats=[convert(t.text) for t in thrs_rm],
            opportunities=[convert(o.text) for o in opps_rm],
            observations=[convert(t) for t in obs_text],
        )
    return PositionDescription(
        threats=[t.text for t in thrs_rm],
        opportunities=[o.text for o in opps_rm],
        observations=obs_text,
    )


def describe_position(
    tree: GameTree, node: GameNode, *, tense: str = "present",
) -> PositionDescription:
    """Describe what this position looks like -- used for the Position section.

    Renders ALL active motifs via the registry and categorizes into three
    buckets. Adds non-tactic observations to the observations list.

    Args:
        tense: "present" (default) or "past". When "past", all descriptions
               are converted to past tense for the Position Before section.
    """
    student_is_white = tree.player_color == chess.WHITE
    return describe_position_from_report(node.report, student_is_white, tense=tense)


# ---------------------------------------------------------------------------
# False discovered attack filter
# ---------------------------------------------------------------------------

def _blocker_is_move_dest(
    key: tuple,
    tactics: TacticalMotifs,
    move_dest: str,
) -> bool:
    """Check if a discovered-attack key's blocker square is the move destination.

    When a piece moves ONTO a slider ray, the after-position detects a
    DiscoveredAttack with the arriving piece as "blocker". But nothing was
    "discovered" — the piece arrived there, it didn't move away. Filter these.
    """
    if key[0] != "discovered":
        return False
    slider_sq, target_sq = key[1], key[2]
    for da in tactics.discovered_attacks:
        if da.slider_square == slider_sq and da.target_square == target_sq and da.blocker_square == move_dest:
            return True
    return False


# ---------------------------------------------------------------------------
# Change descriptions
# ---------------------------------------------------------------------------

def describe_changes(
    tree: GameTree,
    node: GameNode,
    max_plies: int = 3,
    *,
    is_played_move: bool = False,
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
    seen_observations: set[str] = set()

    # Walk the continuation chain (node itself + up to max_plies-1 children)
    chain = _get_continuation_chain(node, max_depth=max_plies - 1)

    prev_tactics = node.parent.tactics
    # Track motifs already seen in parent to prevent repetition across plies
    seen_motif_keys: set[tuple] = all_tactic_keys(prev_tactics)

    for i, chain_node in enumerate(chain):
        current_tactics = chain_node.tactics
        diff = diff_tactics(prev_tactics, current_tactics)
        new_types = _new_motif_types(diff)

        # Filter new_keys to exclude motifs we've already rendered (from parent)
        # This prevents "pin of f7 to g8" from appearing in multiple plies
        # when the parent position already has that pin
        filtered_new_keys = diff.new_keys - seen_motif_keys

        # Filter out false discovered attacks: when a piece moves ONTO a
        # ray, the after-position has a DiscoveredAttack with the arriving
        # piece as "blocker", but nothing was actually "discovered".
        if chain_node.move is not None:
            move_dest = chess.square_name(chain_node.move.to_square)
            filtered_new_keys = {
                k for k in filtered_new_keys
                if not _blocker_is_move_dest(k, current_tactics, move_dest)
            }

        # Render motifs via registry
        is_future = i > 0
        ctx = RenderContext(
            student_is_white=student_is_white,
            player_color=player_color,
            mode=RenderMode.THREAT if is_future else RenderMode.OPPORTUNITY,
            render_config=RenderConfig(),
        )
        opps_rm, thrs_rm, obs_rm, rendered_keys = render_motifs(
            current_tactics, new_types, ctx, new_keys=filtered_new_keys,
            suppress_unsound_opps=(not is_played_move),
        )

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

            # Validate motifs from alternative lines before wrapping (prevent hallucination)
            for desc in opp_texts:
                if _validate_motif_text(desc, chain_node.board):
                    wrapped = f"If {numbered}, {desc}"
                    all_opportunities.append(wrapped)
            for desc in thr_texts:
                if _validate_motif_text(desc, chain_node.board):
                    wrapped = f"If {numbered}, {desc}"
                    all_threats.append(wrapped)

        # Observations: only from the immediate move (i=0). Observations from
        # deeper continuation plies describe hypothetical future positions
        # and lack context, causing non-existent piece references.
        if i == 0:
            for r in obs_rm:
                if r.text not in seen_observations:
                    seen_observations.add(r.text)
                    all_observations.append(r.text)

        prev_tactics = current_tactics
        # Update seen motifs for next iteration (prevent same motif across multiple plies)
        # Bug 2 fix: only track motifs that were actually rendered, not all
        # motifs in the position. This ensures re-emerging motifs (ones that
        # disappear and reappear) are reported again.
        seen_motif_keys.update(rendered_keys)

    return all_opportunities, all_threats, all_observations
