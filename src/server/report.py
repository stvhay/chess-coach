"""Coaching report serializer (Layer 1).

DFS walk over the GameTree that owns section structure. No chess knowledge —
calls Layer 2 description functions at each node and arranges sections.

Produces the LLM user prompt from a GameTree.
"""

from __future__ import annotations

import chess
from dataclasses import dataclass, field

from server.analysis import MaterialCount, analyze_material
from server.descriptions import PositionDescription, describe_changes, describe_position
from server.game_tree import (
    GameNode, GameTree, _material_cp, _detect_sacrifice,
    _get_continuation_chain, _PIECE_NAMES as _GAMETREE_PIECE_NAMES,
    _PIECE_VALUES,
)


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


# ---------------------------------------------------------------------------
# Intermediate report dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ContinuationStep:
    """A single ply in a continuation line."""
    numbered: str      # "6...c4" or "7.Qxb6"
    description: str   # "pushes pawn to c4, attacking queen"


@dataclass
class ContinuationAnalysis:
    """Continuation data: steps, material result, warnings."""
    steps: list[ContinuationStep] = field(default_factory=list)
    result: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class MoveReport:
    """Data for the student's played move."""
    numbered_san: str
    classification: str
    changes: PositionDescription
    opponent_responses: list[str]
    continuation: ContinuationAnalysis


@dataclass
class AlternativeReport:
    """Data for one alternative move."""
    label: str
    numbered_san: str
    changes: PositionDescription
    continuation: ContinuationAnalysis


@dataclass
class CoachingReport:
    """Complete intermediate representation of a coaching report."""
    student_color: str
    fen: str
    board_ascii: str | None
    pgn: str
    position: PositionDescription
    move: MoveReport | None
    alternatives: list[AlternativeReport]
    rag_context: str


# ---------------------------------------------------------------------------
# Board rendering
# ---------------------------------------------------------------------------

def _ascii_board(board: chess.Board) -> str:
    """Render board as labeled ASCII diagram."""
    rows = str(board).split("\n")
    labeled = []
    for i, row in enumerate(rows):
        labeled.append(f"  {8 - i} {row}")
    labeled.append("    a b c d e f g h")
    return "\n".join(labeled)


def _should_include_board(player_node: GameNode | None) -> bool:
    """Include board diagram for captures, pawn moves, and promotions.

    These move types involve notation that LLMs frequently misinterpret
    (e.g., confusing 'hxa6' as a rook move instead of a pawn move).
    """
    if player_node is None or player_node.move is None:
        return False
    san = player_node.san
    if not san:
        return False
    if "x" in san:
        return True
    if san[0].islower():
        return True
    if "=" in san:
        return True
    return False


def _collect_continuation(
    node: GameNode,
    move_number: int,
    student_is_white: bool | None,
    is_player_move: bool,
) -> ContinuationAnalysis:
    """Collect structured continuation data from a node's chain."""
    chain = _get_continuation_chain(node)
    eff_student_white = student_is_white if student_is_white is not None else True

    steps: list[ContinuationStep] = []
    if len(chain) > 1:
        for c_node in chain[1:]:
            san = c_node.san
            if not san:
                continue
            parent_fullmove = c_node.parent.board.fullmove_number if c_node.parent else 1
            mover_is_white = not c_node.board.turn
            if mover_is_white:
                numbered = f"{parent_fullmove}.{san}"
            else:
                numbered = f"{parent_fullmove}...{san}"
            desc = _describe_continuation_move(c_node, eff_student_white)
            steps.append(ContinuationStep(numbered=numbered, description=desc))

    result = _describe_result(chain, student_is_white)
    if result.startswith("Result: "):
        result = result[len("Result: "):]

    notes: list[str] = []
    if _detect_sacrifice(chain, node.score_mate):
        if is_player_move:
            notes.append("This line involves a sacrifice (material given up then recovered).")
        else:
            notes.append("This line involves a sacrifice.")

    if is_player_move:
        for idx, c_node in enumerate(chain[1:], start=1):
            if c_node.board.is_checkmate():
                if idx % 2 == 1:
                    notes.append("WARNING: This move leads to checkmate AGAINST the student!")
                    break
    else:
        for idx, c_node in enumerate(chain):
            if c_node.board.is_checkmate():
                if idx % 2 == 0:
                    notes.append("This alternative delivers checkmate for the student!")
                    break
                else:
                    notes.append("WARNING: This alternative leads to checkmate AGAINST the student!")
                    break

    return ContinuationAnalysis(steps=steps, result=result, notes=notes)


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


def _describe_continuation_move(node: GameNode, student_is_white: bool) -> str:
    """Describe what a single continuation move accomplishes.

    Returns a short phrase like "captures knight on e5" or
    "develops bishop to c5, targeting rook on a1".
    Uses neutral language (no "your"/"their") since both sides move.
    """
    if node.move is None or node.parent is None:
        return ""
    board = node.parent.board
    move = node.move
    piece_type = board.piece_type_at(move.from_square)
    piece_name = _GAMETREE_PIECE_NAMES.get(piece_type, "piece") if piece_type else "piece"
    dest = chess.square_name(move.to_square)

    # Who is moving?
    mover_is_white = not node.board.turn  # side that just moved

    # Castling
    if board.is_castling(move):
        return "castles kingside" if chess.square_file(move.to_square) == 6 else "castles queenside"

    is_capture = board.is_capture(move)
    if is_capture:
        if board.is_en_passant(move):
            captured_name = "pawn"
        else:
            captured_type = board.piece_type_at(move.to_square)
            captured_name = _GAMETREE_PIECE_NAMES.get(captured_type, "piece") if captured_type else "piece"
        desc = f"captures {captured_name} on {dest}"
        if move.promotion:
            promo_name = _GAMETREE_PIECE_NAMES.get(move.promotion, "piece")
            desc += f", promoting to {promo_name}"
    elif move.promotion:
        promo_name = _GAMETREE_PIECE_NAMES.get(move.promotion, "piece")
        desc = f"promotes to {promo_name}"
    elif piece_type == chess.PAWN:
        desc = f"pushes pawn to {dest}"
    elif piece_type in (chess.KNIGHT, chess.BISHOP):
        back_rank = 0 if mover_is_white else 7
        if chess.square_rank(move.from_square) == back_rank:
            desc = f"develops {piece_name} to {dest}"
        else:
            desc = f"moves {piece_name} to {dest}"
    else:
        desc = f"moves {piece_name} to {dest}"

    # Check
    if node.board.is_check():
        desc += " with check"
    elif not is_capture:
        # Add insight for non-captures (captures are self-describing)
        insight = _continuation_insight(node.board, move, mover_is_white)
        if insight:
            desc += f", {insight}"

    return desc


def _continuation_insight(after_board: chess.Board, move: chess.Move, mover_is_white: bool) -> str:
    """Find one notable fact about a continuation move, using neutral language.

    Unlike _move_insight (which uses "your"/"their"), this returns neutral
    descriptions suitable for continuation narration.
    """
    to_sq = move.to_square
    attacked = after_board.attacks(to_sq)
    enemy_color = chess.BLACK if mover_is_white else chess.WHITE
    mover_color = chess.WHITE if mover_is_white else chess.BLACK

    # 1. Attacks enemy high-value piece?
    best_target: tuple[int, str] | None = None
    for sq in attacked:
        piece = after_board.piece_at(sq)
        if piece is None or piece.color != enemy_color:
            continue
        val = _PIECE_VALUES.get(piece.piece_type, 0)
        if val >= 3:
            name = _GAMETREE_PIECE_NAMES.get(piece.piece_type, "piece")
            sq_name = chess.square_name(sq)
            candidate = (val, f"attacking {name} on {sq_name}")
            if best_target is None or val > best_target[0]:
                best_target = candidate
    if best_target is not None:
        return best_target[1]

    # 2. Pawn challenges center?
    piece_type = after_board.piece_type_at(to_sq)
    center = {chess.E4, chess.D4, chess.E5, chess.D5}
    if piece_type == chess.PAWN and to_sq in center:
        return "challenging the center"

    # 3. Defends attacked friendly piece?
    for sq in attacked:
        piece = after_board.piece_at(sq)
        if piece is None or piece.color != mover_color:
            continue
        if after_board.is_attacked_by(enemy_color, sq):
            name = _GAMETREE_PIECE_NAMES.get(piece.piece_type, "piece")
            sq_name = chess.square_name(sq)
            return f"defending {name} on {sq_name}"

    return ""


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
# YAML rendering
# ---------------------------------------------------------------------------

def _yaml_section(entries: list[tuple[str, str | list[str]]]) -> str:
    """Render entries as a fenced YAML code block.

    Entries with empty/None values are omitted.
    Returns empty string if all entries are empty.
    """
    body_lines: list[str] = []
    for key, value in entries:
        if isinstance(value, list):
            if not value:
                continue
            body_lines.append(f"{key}:")
            for item in value:
                body_lines.append(f"  - {item}")
        elif value:
            body_lines.append(f"{key}: {value}")
    if not body_lines:
        return ""
    return "```yaml\n" + "\n".join(body_lines) + "\n```"


def _continuation_entries(
    cont: ContinuationAnalysis,
) -> list[tuple[str, str | list[str]]]:
    """Convert ContinuationAnalysis to YAML-renderable entries."""
    entries: list[tuple[str, str | list[str]]] = []
    if cont.steps:
        step_lines = []
        for step in cont.steps:
            if step.description:
                step_lines.append(f"{step.numbered}: {step.description}")
            else:
                step_lines.append(step.numbered)
        entries.append(("continuation", step_lines))
    if cont.result:
        entries.append(("result", cont.result))
    if cont.notes:
        entries.append(("notes", cont.notes))
    return entries


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(
    tree: GameTree,
    quality: str,
    cp_loss: int,
    rag_context: str = "",
) -> CoachingReport:
    """Build a CoachingReport from a GameTree.

    Extracts all structured data needed for rendering.
    """
    player_color = "White" if tree.player_color == chess.WHITE else "Black"
    student_is_white = tree.player_color == chess.WHITE
    decision = tree.decision_point
    move_number = decision.board.fullmove_number
    pgn = _game_pgn(tree)
    fen = decision.board.fen()

    # Position description (past tense for "before the move")
    pos_desc = describe_position(tree, decision, tense="past")

    # Player move
    player_node = tree.player_move_node()
    move_report = None
    if player_node is not None:
        # Brilliancy detection
        alts_for_brilliancy = tree.alternatives()
        player_uci_check = player_node.move.uci() if player_node.move else ""
        alts_for_brilliancy = [a for a in alts_for_brilliancy if a.move.uci() != player_uci_check]
        if (
            alts_for_brilliancy
            and player_node.score_cp is not None
            and alts_for_brilliancy[0].score_cp is not None
        ):
            best_alt_cp = alts_for_brilliancy[0].score_cp
            player_cp = player_node.score_cp
            if student_is_white:
                player_beats_alts = player_cp >= best_alt_cp
            else:
                player_beats_alts = player_cp <= best_alt_cp
            if player_beats_alts:
                quality = "brilliant"

        numbered_move = _format_numbered_move(player_node.san, move_number, student_is_white)
        opps, thrs, obs = describe_changes(tree, player_node, max_plies=2, is_played_move=True)

        opp_responses: list[str] = []
        if tree.opponent_responses:
            for resp in tree.opponent_responses:
                best_marker = " (engine's top choice)" if resp.is_best else ""
                opp_responses.append(f"{resp.san}: {resp.description}{best_marker}")

        continuation = _collect_continuation(
            player_node, move_number, student_is_white, is_player_move=True,
        )
        move_report = MoveReport(
            numbered_san=numbered_move,
            classification=quality,
            changes=PositionDescription(threats=thrs, opportunities=opps, observations=obs),
            opponent_responses=opp_responses,
            continuation=continuation,
        )

    # Board gating
    board_ascii = _ascii_board(decision.board) if _should_include_board(player_node) else None

    # Alternatives — cap by move quality so the LLM gets only what it needs
    alts = tree.alternatives()
    player_uci = player_node.move.uci() if player_node and player_node.move else ""
    alts = [a for a in alts if a.move.uci() != player_uci]

    is_good = quality in ("good", "brilliant")
    _ALT_CAPS = {"blunder": 1, "mistake": 1, "inaccuracy": 2}
    alt_cap = _ALT_CAPS.get(quality, 2)
    alts = alts[:alt_cap]
    alt_reports: list[AlternativeReport] = []
    for i, alt in enumerate(alts):
        if is_good:
            label = "Other option"
        elif i == 0:
            label = "Stronger Alternative"
        else:
            label = "Also considered"

        numbered = _format_numbered_move(
            _describe_capture(alt.san), move_number, student_is_white,
        )
        opps, thrs, obs = describe_changes(tree, alt, max_plies=3)
        continuation = _collect_continuation(
            alt, move_number, student_is_white, is_player_move=False,
        )
        alt_reports.append(AlternativeReport(
            label=label,
            numbered_san=numbered,
            changes=PositionDescription(threats=thrs, opportunities=opps, observations=obs),
            continuation=continuation,
        ))

    return CoachingReport(
        student_color=player_color,
        fen=fen,
        board_ascii=board_ascii,
        pgn=pgn,
        position=pos_desc,
        move=move_report,
        alternatives=alt_reports,
        rag_context=rag_context,
    )


# ---------------------------------------------------------------------------
# Renderer: Markdown + YAML code blocks
# ---------------------------------------------------------------------------

def render_report(report: CoachingReport) -> str:
    """Render a CoachingReport as Markdown with fenced YAML data blocks."""
    parts: list[str] = []

    # Header
    header = f"Student plays as {report.student_color}"
    if report.board_ascii is not None:
        header += f": {report.fen}"
    parts.append(header)

    # Board diagram (gated)
    if report.board_ascii is not None:
        parts.append(f"\n```chessboard\n{report.board_ascii}\n```")

    # PGN
    if report.pgn:
        parts.append(f"\n{report.pgn}")

    # Position YAML block
    pos_yaml = _yaml_section([
        ("threats", report.position.threats),
        ("opportunities", report.position.opportunities),
        ("observations", report.position.observations),
    ])
    if pos_yaml:
        parts.append(f"\n{pos_yaml}")

    # Move played
    if report.move is not None:
        m = report.move
        parts.append(f"\n# Move Played: {m.numbered_san} [{m.classification}]")

        entries: list[tuple[str, str | list[str]]] = []
        if m.changes.threats:
            entries.append(("new_threats", m.changes.threats))
        if m.changes.opportunities:
            entries.append(("new_opportunities", m.changes.opportunities))
        if m.changes.observations:
            entries.append(("new_observations", m.changes.observations))
        if m.opponent_responses:
            entries.append(("opponent_responses", m.opponent_responses))
        entries.extend(_continuation_entries(m.continuation))

        yaml_block = _yaml_section(entries)
        if yaml_block:
            parts.append(f"\n{yaml_block}")

    # Alternatives
    for alt in report.alternatives:
        parts.append(f"\n# {alt.label}: {alt.numbered_san}")

        entries = []
        if alt.changes.threats:
            entries.append(("new_threats", alt.changes.threats))
        if alt.changes.opportunities:
            entries.append(("new_opportunities", alt.changes.opportunities))
        if alt.changes.observations:
            entries.append(("new_observations", alt.changes.observations))
        entries.extend(_continuation_entries(alt.continuation))

        yaml_block = _yaml_section(entries)
        if yaml_block:
            parts.append(f"\n{yaml_block}")

    # RAG context
    if report.rag_context:
        parts.append(f"\n# Context\n\n{report.rag_context}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def serialize_report(
    tree: GameTree,
    quality: str,
    cp_loss: int,
    rag_context: str = "",
) -> str:
    """Serialize a GameTree into a Markdown+YAML LLM prompt.

    Builds an intermediate CoachingReport, then renders it.
    """
    report = build_report(tree, quality, cp_loss, rag_context)
    return render_report(report)
