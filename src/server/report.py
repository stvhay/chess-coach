"""Coaching report serializer (Layer 1).

DFS walk over the GameTree that owns section structure. No chess knowledge —
calls Layer 2 description functions at each node and arranges sections.

Produces the LLM user prompt from a GameTree.
"""

from __future__ import annotations

import chess

from server.analysis import analyze_material
from server.descriptions import describe_changes, describe_position
from server.game_tree import GameNode, GameTree, _material_cp, _detect_sacrifice, _get_continuation_chain


# ---------------------------------------------------------------------------
# Helpers (ported from formatting.py)
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


def _net_material_summary(nodes: list[GameNode], student_is_white: bool | None) -> str:
    """Sum material changes across node chain, produce human-readable summary.

    Returns e.g. "Net: Student wins 1 pawn" or "" if net is 0.
    """
    if not nodes or nodes[0].parent is None:
        return ""

    base = _material_cp(nodes[0].parent.board)
    final = _material_cp(nodes[-1].board)
    total_cp = final - base

    # Flip for black so positive = good for student
    if student_is_white is not None and not student_is_white:
        total_cp = -total_cp
    if abs(total_cp) < _CP_PER_PAWN:
        return ""
    pawns = abs(total_cp) // _CP_PER_PAWN
    direction = "wins" if total_cp > 0 else "loses"
    unit = "pawn" if pawns == 1 else "pawns"
    return f"Net: Student {direction} {pawns} {unit}"


def _format_move_header(san: str, move_number: int, student_is_white: bool | None) -> str:
    """Format move header: '# Move 4. Bb5' or '# Move 4...c6'."""
    desc = _describe_capture(san)
    if student_is_white is None or student_is_white:
        return f"# Move {move_number}. {desc}"
    else:
        return f"# Move {move_number}...{desc}"


def _game_pgn(tree: GameTree) -> str:
    """Generate PGN from root to decision point (excludes student's move)."""
    played = tree.played_line()
    if len(played) <= 1:
        return ""

    parts = []
    for i, node in enumerate(played[1:], start=0):  # skip root
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
    - Position (pre-move description)
    - Move N. SAN (student's move with classification, continuation, changes)
    - Stronger Alternative / Other option (alternatives with continuations)
    - Relevant chess knowledge (RAG)
    """
    lines: list[str] = []
    player_color = "White" if tree.player_color == chess.WHITE else "Black"
    student_is_white = tree.player_color == chess.WHITE
    decision = tree.decision_point
    move_number = decision.board.fullmove_number

    # --- Student color ---
    lines.append(f"Student is playing: {player_color}")

    # --- Game section ---
    pgn = _game_pgn(tree)
    if pgn:
        lines.append("")
        lines.append("# Game")
        lines.append(pgn)
    lines.append("")

    # --- Position ---
    position_desc = describe_position(tree, decision)
    if position_desc:
        lines.append("# Position")
        lines.append(position_desc)
        lines.append("")

    # --- Move Played ---
    player_node = tree.player_move_node()
    if player_node is not None:
        player_san = player_node.san
        lines.append(_format_move_header(player_san, move_number, student_is_white))

        if quality:
            lines.append(f"Move classification: {quality}")

        # Continuation with move numbers
        continuation = _continuation_san(player_node)
        if continuation:
            numbered = _format_pv_with_numbers(
                continuation, move_number,
                student_is_white if student_is_white is not None else True,
            )
            lines.append(f"Likely continuation: {numbered}")

        # Opportunities/threats
        opps, thrs = describe_changes(tree, player_node, max_plies=2)
        if thrs:
            lines.append("Threats:")
            for t in thrs:
                lines.append(f"  - {t}")
        if opps:
            lines.append("Opportunities:")
            for o in opps:
                lines.append(f"  - {o}")

        # Net material
        chain = _get_continuation_chain(player_node)
        net = _net_material_summary(chain, student_is_white)
        if net:
            lines.append(net)

        # Sacrifice detection
        if _detect_sacrifice(chain, player_node.score_mate):
            lines.append("This line involves a sacrifice (material given up then recovered).")

        # Checkmate warnings
        for c_node in chain[1:]:  # skip the move itself (ply 0)
            if c_node.board.is_checkmate():
                # Determine which ply this is (1-indexed from player's move)
                idx = chain.index(c_node)
                if idx % 2 == 1:  # opponent's response leads to checkmate against student
                    lines.append("WARNING: This move leads to checkmate AGAINST the student!")
                    break

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
        lines.append(f"{label}: {_describe_capture(alt_san)}")

        # Continuation
        alt_cont = _continuation_san(alt)
        if alt_cont:
            numbered = _format_pv_with_numbers(
                alt_cont, move_number,
                student_is_white if student_is_white is not None else True,
            )
            lines.append(f"Continuation: {numbered}")

        # Changes
        opps, thrs = describe_changes(tree, alt, max_plies=3)
        if thrs:
            lines.append("Threats:")
            for t in thrs:
                lines.append(f"  - {t}")
        if opps:
            lines.append("Opportunities:")
            for o in opps:
                lines.append(f"  - {o}")

        # Net material
        alt_chain = _get_continuation_chain(alt)
        net = _net_material_summary(alt_chain, student_is_white)
        if net:
            lines.append(net)

        # Sacrifice
        if _detect_sacrifice(alt_chain, alt.score_mate):
            lines.append("This line involves a sacrifice.")

        # Checkmate detection
        for c_node in alt_chain:
            if c_node.board.is_checkmate():
                idx = alt_chain.index(c_node)
                if idx % 2 == 0:
                    lines.append("This alternative delivers checkmate for the student!")
                    break
                else:
                    lines.append("WARNING: This alternative leads to checkmate AGAINST the student!")
                    break

        lines.append("")

    # --- RAG context ---
    if rag_context:
        lines.append(f"Relevant chess knowledge:\n{rag_context}")

    return "\n".join(lines)
