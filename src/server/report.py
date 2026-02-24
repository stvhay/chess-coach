"""Coaching report serializer (Layer 1).

DFS walk over the GameTree that owns section structure. No chess knowledge —
calls Layer 2 description functions at each node and arranges sections.

Produces the LLM user prompt from a GameTree.
"""

from __future__ import annotations

import chess

from server.analysis import MaterialCount, analyze_material
from server.descriptions import describe_changes, describe_position
from server.game_tree import GameNode, GameTree, _material_cp, _detect_sacrifice, _get_continuation_chain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _format_pv_with_numbers(pv_san: list[str], fullmove: int, white_starts: bool) -> str:
    """Format a PV continuation with move numbers.

    Args:
        pv_san: list of SAN moves (continuation only, student's move excluded)
        fullmove: fullmove number of the student's move
        white_starts: True if the student is White (so continuation starts with Black)
    """
    if not pv_san:
        return ""
    parts = []
    if white_starts:
        move_num = fullmove
        is_white_turn = False
    else:
        move_num = fullmove + 1
        is_white_turn = True

    for san in pv_san:
        if is_white_turn:
            parts.append(f"{move_num}.{san}")
        else:
            if not parts:
                parts.append(f"{move_num}...{san}")
            else:
                parts.append(san)
            move_num += 1
        is_white_turn = not is_white_turn

    return " ".join(parts)


def _format_numbered_move(san: str, move_number: int, student_is_white: bool | None) -> str:
    """Format a move with number: '3. Nxe5' or '3...c6'."""
    if student_is_white is None or student_is_white:
        return f"{move_number}. {san}"
    else:
        return f"{move_number}...{san}"


def _append_categorized(lines: list[str], header: str, items: list[str]) -> None:
    """Append 'Header:\\n  - item\\n...' if items non-empty."""
    if not items:
        return
    lines.append(f"{header}:")
    for item in items:
        lines.append(f"  - {item}")


def _append_continuation_analysis(
    lines: list[str],
    node: GameNode,
    move_number: int,
    student_is_white: bool | None,
    is_player_move: bool,
) -> None:
    """Append continuation, material result, sacrifice, and checkmate annotations.

    Shared between player move and alternative sections.
    """
    # Continuation with move numbers
    continuation = _continuation_san(node)
    if continuation:
        numbered = _format_pv_with_numbers(
            continuation, move_number,
            student_is_white if student_is_white is not None else True,
        )
        lines.append(f"\nContinuation: {numbered}")

    # Material result (piece-level)
    chain = _get_continuation_chain(node)
    result = _describe_result(chain, student_is_white)
    if result:
        lines.append(f"\n{result}")

    # Sacrifice detection
    if _detect_sacrifice(chain, node.score_mate):
        if is_player_move:
            lines.append("\nThis line involves a sacrifice (material given up then recovered).")
        else:
            lines.append("\nThis line involves a sacrifice.")

    # Checkmate detection
    if is_player_move:
        for idx, c_node in enumerate(chain[1:], start=1):
            if c_node.board.is_checkmate():
                if idx % 2 == 1:
                    lines.append("\nWARNING: This move leads to checkmate AGAINST the student!")
                    break
    else:
        for idx, c_node in enumerate(chain):
            if c_node.board.is_checkmate():
                if idx % 2 == 0:
                    lines.append("\nThis alternative delivers checkmate for the student!")
                    break
                else:
                    lines.append("\nWARNING: This alternative leads to checkmate AGAINST the student!")
                    break


def _game_pgn(tree: GameTree) -> str:
    """Generate PGN from root to decision point (excludes student's move)."""
    played = tree.played_line()
    if len(played) <= 1:
        return ""

    parts = []
    for i, node in enumerate(played[1:]):  # skip root
        san = node.san
        if not san:
            continue
        if i % 2 == 0:
            parts.append(f"{i // 2 + 1}. {san}")
        else:
            parts.append(san)
    return " ".join(parts)


def _continuation_san(node: GameNode, max_ply: int = 10) -> list[str]:
    """Get SAN moves of the continuation chain from a node (excluding the node itself)."""
    sans = []
    current = node
    for _ in range(max_ply):
        if not current.children:
            break
        current = current.children[0]
        san = current.san
        if san:
            sans.append(san)
    return sans


# ---------------------------------------------------------------------------
# Material result description (piece-level)
# ---------------------------------------------------------------------------

_PIECE_SINGULAR = {"queens": "queen", "rooks": "rook", "bishops": "bishop", "knights": "knight", "pawns": "pawn"}


def _piece_diff(before: MaterialCount, after: MaterialCount) -> dict[str, int]:
    """Per-piece-type change: positive = gained, negative = lost."""
    return {
        "queens": after.queens - before.queens,
        "rooks": after.rooks - before.rooks,
        "bishops": after.bishops - before.bishops,
        "knights": after.knights - before.knights,
        "pawns": after.pawns - before.pawns,
    }


def _net_piece_diff(student_diff: dict[str, int], opponent_diff: dict[str, int]) -> dict[str, int]:
    """Net per-piece change from the student's perspective.

    Positive = student gained more than opponent (e.g. both lose a queen
    but student also captures a pawn → pawns = +1).
    """
    return {k: student_diff[k] - opponent_diff[k] for k in student_diff}


def _describe_piece_changes(diff: dict[str, int]) -> str:
    """Describe losses/gains as human-readable text.

    Returns e.g. "a rook and pawn" or "a knight".
    """
    parts: list[str] = []
    for piece_type in ("queens", "rooks", "bishops", "knights", "pawns"):
        count = abs(diff.get(piece_type, 0))
        if count == 0:
            continue
        if count == 1:
            parts.append(f"a {_PIECE_SINGULAR[piece_type]}")
        else:
            parts.append(f"{count} {piece_type}")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _describe_result(nodes: list[GameNode], student_is_white: bool | None) -> str:
    """Describe the material result of a continuation using piece-level diffs.

    Returns e.g. "Result: Student wins a knight." or "Result: Equal material."
    """
    if not nodes or nodes[0].parent is None:
        return ""

    start_board = nodes[0].parent.board
    end_board = nodes[-1].board

    start_mat = analyze_material(start_board)
    end_mat = analyze_material(end_board)

    # Calculate per-side piece diffs
    if student_is_white is None or student_is_white:
        student_before = start_mat.white
        student_after = end_mat.white
        opponent_before = start_mat.black
        opponent_after = end_mat.black
    else:
        student_before = start_mat.black
        student_after = end_mat.black
        opponent_before = start_mat.white
        opponent_after = end_mat.white

    student_diff = _piece_diff(student_before, student_after)
    opponent_diff = _piece_diff(opponent_before, opponent_after)

    # Net diff: positive = student gained more than opponent
    net = _net_piece_diff(student_diff, opponent_diff)

    gains = {k: v for k, v in net.items() if v > 0}
    losses = {k: -v for k, v in net.items() if v < 0}

    gains_desc = _describe_piece_changes(gains)
    losses_desc = _describe_piece_changes(losses)

    if gains_desc and losses_desc:
        return f"Result: Student trades {losses_desc} for {gains_desc}."
    if gains_desc:
        return f"Result: Student wins {gains_desc}."
    if losses_desc:
        return f"Result: Student loses {losses_desc}."

    # No net piece changes — check CP for promotions etc.
    start_cp = _material_cp(start_board)
    end_cp = _material_cp(end_board)
    net_cp = end_cp - start_cp
    if student_is_white is not None and not student_is_white:
        net_cp = -net_cp

    if abs(net_cp) >= 50:
        pawns = abs(net_cp) // _CP_PER_PAWN
        unit = "pawn" if pawns == 1 else "pawns"
        if net_cp > 0:
            return f"Result: Student wins {pawns} {unit}."
        return f"Result: Student loses {pawns} {unit}."

    return "Result: No material changes."


# ---------------------------------------------------------------------------
# Main serializer
# ---------------------------------------------------------------------------

def serialize_report(
    tree: GameTree,
    quality: str,
    cp_loss: int,
    rag_context: str = "",
) -> str:
    """Serialize a GameTree into a sectioned LLM prompt.

    Structure:
    - Student color
    - Game (PGN to decision point)
    - Position Before {color}'s Move (three-bucket description)
    - Student Move (classification, changes, continuation, result)
    - Stronger Alternative / Also considered / Other option
    - Relevant chess knowledge (RAG)
    """
    lines: list[str] = []
    player_color = "White" if tree.player_color == chess.WHITE else "Black"
    student_is_white = tree.player_color == chess.WHITE
    decision = tree.decision_point
    move_number = decision.board.fullmove_number

    # --- Student color ---
    lines.append(f"Student is playing: {player_color}")

    pgn = _game_pgn(tree)
    lines.append("")

    # --- Position Before Move ---
    pos_desc = describe_position(tree, decision)
    lines.append(f"# Position Before {player_color}'s Move")
    if pgn:
        lines.append(pgn)
    _append_categorized(lines, "Threats", pos_desc.threats)
    _append_categorized(lines, "Opportunities", pos_desc.opportunities)
    _append_categorized(lines, "Observations", pos_desc.observations)
    lines.append("")

    # --- Student Move ---
    player_node = tree.player_move_node()
    if player_node is not None:
        player_san = player_node.san
        numbered_move = _format_numbered_move(player_san, move_number, student_is_white)
        lines.append("# Student Move")
        lines.append("")
        lines.append(numbered_move)

        if quality:
            lines.append(f"\nMove classification: {quality}")

        # Changes (three-bucket)
        opps, thrs, obs = describe_changes(tree, player_node, max_plies=2)
        _append_categorized(lines, "\nNew Threats", thrs)
        _append_categorized(lines, "\nNew Opportunities", opps)
        _append_categorized(lines, "\nNew Observations", obs)

        _append_continuation_analysis(
            lines, player_node, move_number, student_is_white, is_player_move=True,
        )

        lines.append("")

    # --- Alternatives ---
    alts = tree.alternatives()
    # Filter out player's move if it also appears as engine line
    player_uci = player_node.move.uci() if player_node and player_node.move else ""
    alts = [a for a in alts if a.move.uci() != player_uci]

    is_good = quality in ("good", "brilliant")
    for i, alt in enumerate(alts):
        alt_san = alt.san
        if is_good:
            label = "# Other option"
        elif i == 0:
            label = "# Stronger Alternative"
        else:
            label = "# Also considered"
        lines.append(label)
        lines.append("")
        lines.append(_format_numbered_move(
            _describe_capture(alt_san), move_number, student_is_white,
        ))

        # Changes (three-bucket)
        opps, thrs, obs = describe_changes(tree, alt, max_plies=3)
        _append_categorized(lines, "\nNew Threats", thrs)
        _append_categorized(lines, "\nNew Opportunities", opps)
        _append_categorized(lines, "\nNew Observations", obs)

        _append_continuation_analysis(
            lines, alt, move_number, student_is_white, is_player_move=False,
        )

        lines.append("")

    # --- RAG context ---
    if rag_context:
        lines.append(f"Relevant chess knowledge:\n{rag_context}")

    return "\n".join(lines)
