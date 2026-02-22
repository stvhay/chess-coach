"""Prompt formatting helpers and builders for coaching and opponent prompts.

Pure functions that convert structured analysis data into LLM-ready text.
"""

from __future__ import annotations

from server.screener import CoachingContext


def _colored(piece_char: str) -> str:
    """Add color prefix: 'N' → 'White N', 'p' → 'Black P'."""
    color = "White" if piece_char.isupper() else "Black"
    return f"{color} {piece_char.upper()}"


def _is_significant_discovery(da) -> bool:
    """Filter out trivial pawn-reveals-rook x-rays that exist in every position."""
    # Only include if the blocker is a piece (not a pawn) or the target is high-value
    blocker_is_pawn = da.blocker_piece.lower() == "p"
    target_is_valuable = da.target_piece.lower() in ("q", "k", "r")
    return not blocker_is_pawn or target_is_valuable


def _describe_tactics(ann) -> list[str]:
    """Produce human-readable descriptions from tactical motifs on a ply.

    Only describes motif types that are NEW this ply (appeared in ann.new_motifs),
    preventing repetition of already-known tactics across plies.
    """
    descriptions: list[str] = []
    tactics = ann.tactics
    new = set(ann.new_motifs)

    if "fork" in new:
        for fork in tactics.forks:
            targets = ", ".join(fork.targets)
            descriptions.append(
                f"fork by {_colored(fork.forking_piece)} on {fork.forking_square} "
                f"targeting {targets}")

    if "pin" in new:
        for pin in tactics.pins:
            descriptions.append(
                f"pin: {_colored(pin.pinned_piece)} on {pin.pinned_square} pinned by "
                f"{_colored(pin.pinner_piece)} on {pin.pinner_square} to {pin.pinned_to}"
            )

    if "skewer" in new:
        for skewer in tactics.skewers:
            descriptions.append(
                f"skewer by {_colored(skewer.attacker_piece)} on {skewer.attacker_square}: "
                f"{_colored(skewer.front_piece)} on {skewer.front_square}, "
                f"{_colored(skewer.behind_piece)} on {skewer.behind_square}"
            )

    if "hanging_piece" in new:
        for hp in tactics.hanging:
            descriptions.append(f"hanging {_colored(hp.piece)} on {hp.square}")

    if "discovered_attack" in new:
        significant = [da for da in tactics.discovered_attacks if _is_significant_discovery(da)]
        for da in significant[:3]:  # cap at 3 to prevent prompt bloat
            descriptions.append(
                f"discovered attack: {_colored(da.blocker_piece)} on {da.blocker_square} "
                f"reveals {_colored(da.slider_piece)} on {da.slider_square} targeting "
                f"{_colored(da.target_piece)} on {da.target_square}"
            )

    if "checkmate" in new:
        descriptions.append("checkmate")

    if "double_check" in new:
        for dc in tactics.double_checks:
            squares = ", ".join(dc.checker_squares)
            descriptions.append(f"double check from {squares}")

    if "trapped_piece" in new:
        for tp in tactics.trapped_pieces:
            descriptions.append(f"trapped {_colored(tp.piece)} on {tp.square}")

    if "mate_threat" in new:
        for mt in tactics.mate_threats:
            descriptions.append(
                f"{mt.threatening_color} threatens checkmate on {mt.mating_square}")

    if "back_rank_weakness" in new:
        for bw in tactics.back_rank_weaknesses:
            descriptions.append(f"{bw.weak_color}'s back rank is weak (king on {bw.king_square})")

    if "xray_attack" in new:
        for xa in tactics.xray_attacks[:3]:
            descriptions.append(
                f"x-ray: {_colored(xa.slider_piece)} on {xa.slider_square} "
                f"through {_colored(xa.through_piece)} on {xa.through_square} "
                f"targeting {_colored(xa.target_piece)} on {xa.target_square}")

    if "exposed_king" in new:
        for ek in tactics.exposed_kings:
            descriptions.append(
                f"{ek.color}'s king on {ek.king_square} is exposed (advanced, no pawn shield)")

    if "overloaded_piece" in new:
        for op in tactics.overloaded_pieces:
            charges = ", ".join(op.defended_squares)
            descriptions.append(
                f"overloaded {_colored(op.piece)} on {op.square} "
                f"sole defender of {charges}")

    if "capturable_defender" in new:
        for cd in tactics.capturable_defenders:
            descriptions.append(
                f"capturable defender: {_colored(cd.defender_piece)} on {cd.defender_square} "
                f"defends {_colored(cd.charge_piece)} on {cd.charge_square}")

    # Track which motif types got detailed descriptions
    described_types: set[str] = set()
    if "fork" in new and tactics.forks:
        described_types.add("fork")
    if "pin" in new and tactics.pins:
        described_types.add("pin")
    if "skewer" in new and tactics.skewers:
        described_types.add("skewer")
    if "hanging_piece" in new and tactics.hanging:
        described_types.add("hanging_piece")
    if "discovered_attack" in new:
        described_types.add("discovered_attack")
    if "checkmate" in new:
        described_types.add("checkmate")
    for motif in ("double_check", "trapped_piece", "mate_threat", "back_rank_weakness",
                  "xray_attack", "exposed_king", "overloaded_piece", "capturable_defender"):
        if motif in new:
            described_types.add(motif)
    for motif in new:
        if motif.startswith("mate_"):
            described_types.add(motif)

    # Fallback: emit bare motif name for any new motifs without structured detail
    for motif in sorted(new - described_types):
        descriptions.append(motif)

    return descriptions


_PIECE_NAMES = {"N": "knight", "B": "bishop", "R": "rook", "Q": "queen", "K": "king"}


def _describe_capture(san: str) -> str:
    """Annotate capture moves to prevent notation confusion.

    "Bxf7+" → "bishop captures on f7 (Bxf7+)"
    "Nxe4"  → "knight captures on e4 (Nxe4)"
    "dxc4"  → "pawn captures on c4 (dxc4)"
    Non-captures are returned unchanged.

    Natural language comes FIRST so the LLM anchors on the
    correct piece role before seeing ambiguous SAN notation.
    """
    if "x" not in san:
        return san
    # The character before 'x' identifies the capturing piece
    idx = san.index("x")
    if idx > 0 and san[idx - 1] in _PIECE_NAMES:
        capturer = _PIECE_NAMES[san[idx - 1]]
    else:
        capturer = "pawn"
    # Destination square is the 2 chars after 'x', ignoring +/#/=
    dest = san[idx + 1:idx + 3]
    return f"{capturer} captures on {dest} ({san})"


def _format_ply_annotations(annotations: list, side_to_move_is_white: bool | None = None) -> list[str]:
    """Format ply annotations, omitting plies with nothing interesting.

    Only includes new tactical motifs and material changes — position
    summaries are provided once at the top of the prompt, not per-ply.

    If side_to_move_is_white is provided, material changes are presented
    from that side's perspective (positive = good for the student).
    """
    lines: list[str] = []
    for ann in annotations:
        parts: list[str] = []

        # Detailed tactical descriptions — only for NEW motif types
        tactic_descs = _describe_tactics(ann)
        if tactic_descs:
            parts.extend(tactic_descs)

        # Skip material changes on checkmate plies — irrelevant and confusing
        is_checkmate = "checkmate" in (ann.new_motifs or [])
        if not is_checkmate and ann.material_change != 0:
            mc = ann.material_change
            # Flip sign for black so positive = good for student
            if side_to_move_is_white is not None and not side_to_move_is_white:
                mc = -mc
            direction = "gains" if mc > 0 else "loses"
            parts.append(f"material {direction} {abs(ann.material_change)} cp")

        # Only emit this ply if there's something to say
        if parts:
            side_label = "student" if ann.ply % 2 == 0 else "opponent"
            lines.append(f"  Ply {ann.ply + 1} ({ann.move_san}, {side_label}): {'; '.join(parts)}")
    return lines


def _position_context(ctx: CoachingContext) -> str:
    """Extract a position summary from the first annotation of the player's line."""
    if ctx.player_move and ctx.player_move.annotations:
        # The first annotation is the position AFTER the player's move
        return ctx.player_move.annotations[0].position_summary
    return ""


def format_coaching_prompt(ctx: CoachingContext) -> str:
    """Convert annotated coaching context to LLM user prompt.

    Produces structured text with per-ply annotations so the LLM
    only references computed facts. Omits empty plies to reduce noise.
    Includes position summary so the LLM knows what's on the board.
    """
    lines: list[str] = []

    # Context header
    if ctx.player_color:
        lines.append(f"Student is playing: {ctx.player_color}")
    if ctx.quality:
        lines.append(f"Move classification: {ctx.quality}")

    # Position context — what's actually on the board
    pos_ctx = _position_context(ctx)
    if pos_ctx:
        lines.append(f"Position: {pos_ctx}")
    lines.append("")

    # Determine side for material perspective
    student_is_white = ctx.player_color == "White" if ctx.player_color else None

    # Player's move
    if ctx.player_move:
        pm = ctx.player_move
        lines.append(f"Student played: {_describe_capture(pm.first_move_san)}")
        if pm.pv_san and len(pm.pv_san) > 1:
            lines.append(f"  Likely continuation: {' '.join(pm.pv_san[1:])}")
        ply_lines = _format_ply_annotations(pm.annotations, student_is_white)
        if ply_lines:
            lines.extend(ply_lines)
        else:
            lines.append("  No notable tactics in this line.")

        if pm.has_sacrifice:
            lines.append("  ★ This line involves a sacrifice (material given up then recovered).")

        # Check if opponent delivers checkmate in student's continuation
        for ann in pm.annotations:
            if "checkmate" in (ann.new_motifs or []) and ann.ply % 2 == 1:
                lines.append("  ⚠ This move leads to checkmate AGAINST the student!")
                break
        lines.append("")

    # Best alternative lines — filter out the player's own move
    player_uci = ctx.player_move.first_move_uci if ctx.player_move else ""
    alternatives = [alt for alt in ctx.best_lines if alt.first_move_uci != player_uci]

    is_good = ctx.quality in ("good", "brilliant")
    for i, alt in enumerate(alternatives):
        if is_good:
            label = "Other option"
        elif i == 0:
            label = "Stronger alternative"
        else:
            label = "Also considered"
        lines.append(f"{label}: {_describe_capture(alt.first_move_san)}")
        if alt.pv_san and len(alt.pv_san) > 1:
            lines.append(f"  Likely continuation: {' '.join(alt.pv_san[1:])}")
        ply_lines = _format_ply_annotations(alt.annotations, student_is_white)
        if ply_lines:
            lines.extend(ply_lines)
        else:
            lines.append("  No notable tactics in this line.")

        if alt.has_sacrifice:
            lines.append("  ★ This line involves a sacrifice.")

        # Check if student delivers checkmate in this alternative
        for ann in alt.annotations:
            if "checkmate" in (ann.new_motifs or []) and ann.ply % 2 == 0:
                lines.append("  ★ This alternative delivers checkmate for the student!")
                break

        # Check if opponent delivers checkmate in this alternative
        for ann in alt.annotations:
            if "checkmate" in (ann.new_motifs or []) and ann.ply % 2 == 1:
                lines.append("  ⚠ This alternative leads to checkmate AGAINST the student!")
                break
        lines.append("")

    # RAG context
    if ctx.rag_context:
        lines.append(f"Relevant chess knowledge:\n{ctx.rag_context}")

    return "\n".join(lines)


def build_opponent_prompt(ctx) -> str:
    """Build the user-message content for opponent move selection.

    Accepts an OpponentMoveContext (imported at call site to avoid
    circular imports with llm.py).
    """
    lines = [
        f"Position: {ctx.fen}",
        f"Game phase: {ctx.game_phase}",
        f"Student is playing: {ctx.player_color}",
        f"Position summary: {ctx.position_summary}",
        "Candidate moves (all are sound):",
    ]
    for c in ctx.candidates:
        score_str = f"{c['score_cp']} cp" if c.get("score_cp") is not None else "mate"
        lines.append(f"  {c['san']} ({score_str})")
    lines.append("Select the most pedagogically valuable move. Respond with JSON only.")
    return "\n".join(lines)
