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
    blocker_is_pawn = da.blocker_piece.lower() == "p"
    target_is_valuable = da.target_piece.lower() in ("q", "k", "r")
    return not blocker_is_pawn or target_is_valuable


def _piece_is_students(piece_char: str, student_is_white: bool | None) -> bool:
    """Is this piece the student's? Uppercase = White pieces."""
    if student_is_white is None:
        return True
    return piece_char.isupper() == student_is_white


def _color_is_students(color_str: str, player_color: str) -> bool:
    """Is this color string the student's color?"""
    return color_str.lower() == player_color.lower()


def _ray_direction(from_sq: str, to_sq: str) -> tuple[int, int]:
    """Normalized compass direction between two algebraic squares."""
    df = ord(to_sq[0]) - ord(from_sq[0])
    dr = int(to_sq[1]) - int(from_sq[1])
    return ((1 if df > 0 else -1) if df else 0,
            (1 if dr > 0 else -1) if dr else 0)


def _deduplicate_line_motifs(tactics):
    """Remove geometric duplicates among pins, skewers, and x-rays.

    Group by (attacker_square, normalized_direction) and keep highest priority:
    absolute pin > non-absolute pin > skewer > x-ray.

    Returns (keep_pins, keep_skewers, keep_xrays) — filtered lists.
    """
    # Build groups: key -> list of (priority, type, object)
    # Lower priority number = higher importance
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


def _classify_and_describe(ann, tactics, student_is_white: bool | None, player_color: str) -> tuple[list[str], list[str]]:
    """Classify motifs as opportunities or threats with natural-language descriptions.

    Returns (opportunities, threats).
    """
    new = set(ann.new_motifs)
    opportunities: list[str] = []
    threats: list[str] = []
    described: set[str] = set()  # track which motifs produced output

    # Deduplicate ray-based motifs
    keep_pins, keep_skewers, keep_xrays = _deduplicate_line_motifs(tactics)
    keep_pin_set = set(id(p) for p in keep_pins)
    keep_skewer_set = set(id(s) for s in keep_skewers)
    keep_xray_set = set(id(x) for x in keep_xrays)

    if "fork" in new:
        for fork in tactics.forks:
            described.add("fork")
            is_student = _piece_is_students(fork.forking_piece, student_is_white)
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
            # Fork targeting king: wins the other piece
            if fork.target_pieces and any(tp.upper() == "K" for tp in fork.target_pieces):
                other = [f"{_colored(tp)}" for tp in fork.target_pieces if tp.upper() != "K"]
                if other:
                    desc += f" (wins the {other[0]})"
            if is_student:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "pin" in new:
        described.add("pin")  # mark described before loop — dedup may filter all instances
        for pin in tactics.pins:
            if id(pin) not in keep_pin_set:
                continue
            is_student = _piece_is_students(pin.pinner_piece, student_is_white)
            abs_label = " (cannot move)" if pin.is_absolute else ""
            if pin.pinned_to_piece:
                to_desc = f"{_colored(pin.pinned_to_piece)} on {pin.pinned_to}"
            else:
                to_desc = pin.pinned_to
            desc = (f"pin: {_colored(pin.pinned_piece)} on {pin.pinned_square} pinned by "
                    f"{_colored(pin.pinner_piece)} on {pin.pinner_square} to {to_desc}"
                    f"{abs_label}")
            if is_student:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "skewer" in new:
        described.add("skewer")  # mark described before loop — dedup may filter all instances
        for skewer in tactics.skewers:
            if id(skewer) not in keep_skewer_set:
                continue
            is_student = _piece_is_students(skewer.attacker_piece, student_is_white)
            desc = (f"skewer by {_colored(skewer.attacker_piece)} on {skewer.attacker_square}: "
                    f"{_colored(skewer.front_piece)} on {skewer.front_square}, "
                    f"{_colored(skewer.behind_piece)} on {skewer.behind_square}")
            if is_student:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "hanging_piece" in new:
        for hp in tactics.hanging:
            described.add("hanging_piece")
            # Hanging opponent piece = opportunity, hanging student piece = threat
            if hp.color:
                is_opponents = not _color_is_students(hp.color, player_color)
            else:
                is_opponents = not _piece_is_students(hp.piece, student_is_white)
            if hp.can_retreat:
                desc = f"{_colored(hp.piece)} on {hp.square} is undefended (must move)"
            else:
                desc = f"hanging {_colored(hp.piece)} on {hp.square}"
            if is_opponents:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "discovered_attack" in new:
        significant = [da for da in tactics.discovered_attacks if _is_significant_discovery(da)]
        for da in significant[:3]:
            described.add("discovered_attack")
            is_student = _piece_is_students(da.slider_piece, student_is_white)
            desc = (f"discovered attack: {_colored(da.blocker_piece)} on {da.blocker_square} "
                    f"reveals {_colored(da.slider_piece)} on {da.slider_square} targeting "
                    f"{_colored(da.target_piece)} on {da.target_square}")
            if is_student:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "double_check" in new:
        for dc in tactics.double_checks:
            described.add("double_check")
            squares = ", ".join(dc.checker_squares)
            desc = f"double check from {squares}"
            if ann.ply % 2 == 0:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "trapped_piece" in new:
        for tp in tactics.trapped_pieces:
            described.add("trapped_piece")
            is_opponents = not _piece_is_students(tp.piece, student_is_white)
            desc = f"trapped {_colored(tp.piece)} on {tp.square}"
            if is_opponents:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "mate_threat" in new:
        for mt in tactics.mate_threats:
            described.add("mate_threat")
            is_student = _color_is_students(mt.threatening_color, player_color)
            desc = f"{mt.threatening_color} threatens checkmate on {mt.mating_square}"
            if is_student:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "back_rank_weakness" in new:
        for bw in tactics.back_rank_weaknesses:
            described.add("back_rank_weakness")
            is_opponents = not _color_is_students(bw.weak_color, player_color)
            desc = f"{bw.weak_color}'s back rank is weak (king on {bw.king_square})"
            if is_opponents:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "xray_attack" in new:
        described.add("xray_attack")  # mark described before loop — dedup may filter all instances
        for xa in tactics.xray_attacks[:3]:
            if id(xa) not in keep_xray_set:
                continue
            is_student = _piece_is_students(xa.slider_piece, student_is_white)
            desc = (f"x-ray: {_colored(xa.slider_piece)} on {xa.slider_square} "
                    f"through {_colored(xa.through_piece)} on {xa.through_square} "
                    f"targeting {_colored(xa.target_piece)} on {xa.target_square}")
            if is_student:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "exposed_king" in new:
        for ek in tactics.exposed_kings:
            described.add("exposed_king")
            is_opponents = not _color_is_students(ek.color, player_color)
            desc = f"{ek.color}'s king on {ek.king_square} is exposed (advanced, no pawn shield)"
            if is_opponents:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "overloaded_piece" in new:
        for op in tactics.overloaded_pieces:
            described.add("overloaded_piece")
            is_opponents = not _piece_is_students(op.piece, student_is_white)
            charges = ", ".join(op.defended_squares)
            desc = (f"overloaded {_colored(op.piece)} on {op.square} "
                    f"sole defender of {charges}")
            if is_opponents:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "capturable_defender" in new:
        for cd in tactics.capturable_defenders:
            described.add("capturable_defender")
            is_opponents = not _piece_is_students(cd.defender_piece, student_is_white)
            desc = (f"capturable defender: {_colored(cd.defender_piece)} on {cd.defender_square} "
                    f"defends {_colored(cd.charge_piece)} on {cd.charge_square}")
            if cd.attacker_square:
                desc += (f" — if captured, {_colored(cd.charge_piece)} on "
                         f"{cd.charge_square} is left hanging")
            if is_opponents:
                opportunities.append(desc)
            else:
                threats.append(desc)

    if "checkmate" in new:
        described.add("checkmate")
        # Checkmate classified by which ply it occurs on
        if ann.ply % 2 == 0:
            opportunities.append("checkmate")
        else:
            threats.append("checkmate")

    # Fallback: bare motif names for anything not described by structured handlers
    for motif in sorted(new - described):
        if motif.startswith("mate_"):
            continue
        opportunities.append(motif)

    return opportunities, threats


_PIECE_NAMES = {"N": "knight", "B": "bishop", "R": "rook", "Q": "queen", "K": "king"}
_CP_PER_PAWN = 100


def _describe_capture(san: str) -> str:
    """Annotate capture moves to prevent notation confusion.

    "Bxf7+" → "bishop captures on f7 (Bxf7+)"
    "Nxe4"  → "knight captures on e4 (Nxe4)"
    "dxc4"  → "pawn captures on c4 (dxc4)"
    Non-captures are returned unchanged.
    """
    if "x" not in san:
        return san
    idx = san.index("x")
    if idx > 0 and san[idx - 1] in _PIECE_NAMES:
        capturer = _PIECE_NAMES[san[idx - 1]]
    else:
        capturer = "pawn"
    dest = san[idx + 1:idx + 3]
    return f"{capturer} captures on {dest} ({san})"


def _net_material_summary(annotations: list, student_is_white: bool | None) -> str:
    """Sum material_change across annotations and produce a human-readable summary.

    Returns e.g. "Net: Student wins 1 pawn" or "" if net is 0.
    """
    total_cp = sum(ann.material_change for ann in annotations)
    # Flip for black so positive = good for student
    if student_is_white is not None and not student_is_white:
        total_cp = -total_cp
    if abs(total_cp) < _CP_PER_PAWN:
        return ""
    pawns = abs(total_cp) // _CP_PER_PAWN
    direction = "wins" if total_cp > 0 else "loses"
    unit = "pawn" if pawns == 1 else "pawns"
    return f"Net: Student {direction} {pawns} {unit}"


def _format_pv_with_numbers(pv_san: list[str], fullmove: int, white_starts: bool) -> str:
    """Format a PV with move numbers.

    Args:
        pv_san: list of SAN moves (continuation only, student's move excluded)
        fullmove: fullmove number of the student's move
        white_starts: True if the student is White (so continuation starts with Black)

    Returns e.g. "4...c6 5.Be2" or "5.d4 exd4 6.c3"
    """
    if not pv_san:
        return ""
    parts = []
    # After student's move:
    # If student is White, next ply is Black → starts with "{N}..."
    # If student is Black, next ply is White → starts with "{N+1}."
    if white_starts:
        # Continuation starts at Black's response
        move_num = fullmove
        is_white_turn = False
    else:
        # Continuation starts at White's next move
        move_num = fullmove + 1
        is_white_turn = True

    for san in pv_san:
        if is_white_turn:
            parts.append(f"{move_num}.{san}")
        else:
            if not parts:
                # First move is Black — need ellipsis
                parts.append(f"{move_num}...{san}")
            else:
                parts.append(san)
            move_num += 1
        is_white_turn = not is_white_turn

    return " ".join(parts)


def _format_opportunities_threats(
    annotations: list,
    student_is_white: bool | None,
    player_color: str,
    max_plies: int = 3,
    pv_san: list[str] | None = None,
    fullmove: int = 1,
) -> list[str]:
    """Collect opportunities and threats across annotations, deduplicate, format.

    For ply 0 annotations: describe motifs as-is (direct consequence of the move).
    For ply 1+ annotations: describe as opponent/player threats using chess language.
    """
    all_opportunities: list[str] = []
    all_threats: list[str] = []
    opponent_color = "Black" if player_color == "White" else "White"

    for ann in annotations[:max_plies]:
        if not ann.new_motifs:
            continue

        opps, thrs = _classify_and_describe(ann, ann.tactics, student_is_white, player_color)

        if ann.ply == 0:
            # Direct consequence of the move — describe as-is
            all_opportunities.extend(opps)
            all_threats.extend(thrs)
        else:
            # Future ply — describe as threats using chess language
            # Get the numbered move for this ply
            if pv_san and ann.ply < len(pv_san) + 1:
                # pv_san[0] is student's move (ply 0), pv_san[1] is ply 1, etc.
                # But pv_san passed here starts from [1:] (continuation only)
                ply_idx = ann.ply - 1  # index into continuation
                if ply_idx < len(pv_san) if pv_san else False:
                    move_san = pv_san[ply_idx]
                    # Determine who plays this ply
                    if student_is_white:
                        # ply 1 = Black, ply 2 = White, etc.
                        ply_is_white = (ann.ply % 2 == 0)
                    else:
                        # ply 1 = White, ply 2 = Black, etc.
                        ply_is_white = (ann.ply % 2 == 1)

                    if ply_is_white:
                        move_num = fullmove + (ann.ply + 1) // 2 if student_is_white else fullmove + ann.ply // 2
                        numbered = f"{move_num}.{move_san}"
                    else:
                        move_num = fullmove + ann.ply // 2 if student_is_white else fullmove + (ann.ply + 1) // 2
                        numbered = f"{move_num}...{move_san}"

                    # Who is threatening? The player of this ply.
                    threatener = "White" if ply_is_white else "Black"

                    # Wrap each description as a threat
                    for desc in opps + thrs:
                        wrapped = f"{threatener} threatens {numbered}, {desc}"
                        if threatener == player_color:
                            all_opportunities.append(wrapped)
                        else:
                            all_threats.append(wrapped)
                else:
                    all_opportunities.extend(opps)
                    all_threats.extend(thrs)
            else:
                all_opportunities.extend(opps)
                all_threats.extend(thrs)

    lines: list[str] = []
    if all_threats:
        lines.append("Threats:")
        for t in all_threats:
            lines.append(f"  - {t}")
    if all_opportunities:
        lines.append("Opportunities:")
        for o in all_opportunities:
            lines.append(f"  - {o}")
    return lines


def _format_move_header(san: str, move_number: int, student_is_white: bool | None) -> str:
    """Format move header: '# Move 4. Bb5' or '# Move 4...c6'."""
    desc = _describe_capture(san)
    if student_is_white is None or student_is_white:
        return f"# Move {move_number}. {desc}"
    else:
        return f"# Move {move_number}...{desc}"


def format_coaching_prompt(ctx: CoachingContext) -> str:
    """Convert annotated coaching context to sectioned LLM user prompt.

    Structured as:
    - Student color
    - Game (PGN up to decision point)
    - Position (pre-move summary)
    - Move N. SAN (student's move with classification, continuation, opps/threats)
    - Stronger Alternative(s) (with continuation, opps/threats)
    - Relevant chess knowledge (RAG)
    """
    lines: list[str] = []
    student_is_white = ctx.player_color == "White" if ctx.player_color else None
    player_color = ctx.player_color or "White"

    # --- Student color first ---
    if ctx.player_color:
        lines.append(f"Student is playing: {ctx.player_color}")

    # --- Game section ---
    if ctx.game_pgn:
        lines.append("")
        lines.append("# Game")
        lines.append(ctx.game_pgn)
    lines.append("")

    # --- Position ---
    if ctx.position_summary:
        lines.append("# Position")
        lines.append(ctx.position_summary)
        lines.append("")

    # --- Move Played ---
    if ctx.player_move:
        pm = ctx.player_move
        lines.append(_format_move_header(pm.first_move_san, ctx.move_number, student_is_white))
        if ctx.quality:
            lines.append(f"Move classification: {ctx.quality}")

        # Continuation with move numbers (exclude student's move = pv_san[0])
        continuation = pm.pv_san[1:] if pm.pv_san and len(pm.pv_san) > 1 else []
        if continuation:
            numbered = _format_pv_with_numbers(
                continuation, ctx.move_number, student_is_white or student_is_white is None)
            lines.append(f"Likely continuation: {numbered}")

        # Opportunities/threats from first 2 plies
        ot_lines = _format_opportunities_threats(
            pm.annotations, student_is_white, player_color, max_plies=2,
            pv_san=continuation, fullmove=ctx.move_number)
        if ot_lines:
            lines.extend(ot_lines)

        # Net material
        net = _net_material_summary(pm.annotations, student_is_white)
        if net:
            lines.append(net)

        # Sacrifice
        if pm.has_sacrifice:
            lines.append("This line involves a sacrifice (material given up then recovered).")

        # Checkmate warnings
        for ann in pm.annotations:
            if "checkmate" in (ann.new_motifs or []) and ann.ply % 2 == 1:
                lines.append("WARNING: This move leads to checkmate AGAINST the student!")
                break

        lines.append("")

    # --- Alternatives ---
    player_uci = ctx.player_move.first_move_uci if ctx.player_move else ""
    alternatives = [alt for alt in ctx.best_lines if alt.first_move_uci != player_uci]

    is_good = ctx.quality in ("good", "brilliant")
    for i, alt in enumerate(alternatives):
        if is_good:
            label = "# Other option"
        elif i == 0:
            label = "# Stronger Alternative"
        else:
            label = "# Also considered"
        lines.append(f"{label}: {_describe_capture(alt.first_move_san)}")

        # Continuation with move numbers
        alt_continuation = alt.pv_san[1:] if alt.pv_san and len(alt.pv_san) > 1 else []
        if alt_continuation:
            numbered = _format_pv_with_numbers(
                alt_continuation, ctx.move_number, student_is_white or student_is_white is None)
            lines.append(f"Continuation: {numbered}")

        ot_lines = _format_opportunities_threats(
            alt.annotations, student_is_white, player_color, max_plies=3,
            pv_san=alt_continuation, fullmove=ctx.move_number)
        if ot_lines:
            lines.extend(ot_lines)

        net = _net_material_summary(alt.annotations, student_is_white)
        if net:
            lines.append(net)

        if alt.has_sacrifice:
            lines.append("This line involves a sacrifice.")

        # Student delivers checkmate
        for ann in alt.annotations:
            if "checkmate" in (ann.new_motifs or []) and ann.ply % 2 == 0:
                lines.append("This alternative delivers checkmate for the student!")
                break

        # Opponent delivers checkmate
        for ann in alt.annotations:
            if "checkmate" in (ann.new_motifs or []) and ann.ply % 2 == 1:
                lines.append("WARNING: This alternative leads to checkmate AGAINST the student!")
                break

        lines.append("")

    # --- RAG context ---
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
