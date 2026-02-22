"""LLM orchestrator for chess coaching.

Sends structured move assessment data to a local Ollama instance and
returns natural-language coaching messages.  Falls back gracefully
(returns None) when the LLM is unreachable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from server.screener import CoachingContext


@dataclass
class OpponentMoveContext:
    """Everything the LLM needs to select a teaching move."""
    fen: str
    game_phase: str
    position_summary: str
    candidates: list[dict]   # [{san, uci, score_cp}, ...]
    player_color: str


_SYSTEM_PROMPT = """\
You are a chess coach speaking directly to a student about their move.
Address the student as "you". Be concise: 2-3 sentences.
Be encouraging, not condescending.

STRICT RULES:
- ONLY mention pieces, squares, and tactics that appear in the analysis below.
- If the analysis says "fork" or "pin", you may mention it. If it does not, you must NOT.
- When tactical annotations exist, reference the specific tactic and squares involved.
- If an annotation says "checkmate", that is the most important thing to mention.
- Do NOT invent or guess tactical themes, piece locations, or consequences \
not explicitly listed in the annotations.
- Do NOT mention evaluation numbers or centipawn values.
- If the move classification is "good", affirm the student's choice. Do NOT suggest \
alternatives are better. You may briefly mention other options exist without recommending them.
- If the student's move is a blunder or mistake, clearly explain what was wrong and \
what the stronger alternative achieves using ONLY the listed annotations.
- NEVER recommend an alternative marked with "⚠ This alternative leads to checkmate \
AGAINST the student!" — that move is even worse. If all alternatives lead to checkmate, \
say the position was already lost.
- Do not use markdown formatting.

SEVERITY:
- "blunder": Serious error. Use direct language like "this misses checkmate" or \
"this loses significant material". NEVER say "a bit risky" for a blunder.
- "mistake": Clear error. Explain concretely what was missed.
- "inaccuracy": Noticeable imprecision. Explain what the better move achieves. \
Do NOT say "Great work" or praise an inaccuracy. Do NOT call it "reasonable".
- "good" or "brilliant": Praise the move. Do NOT criticize it.

PERSPECTIVE:
- Each ply is labeled "(student)" or "(opponent)".
- Tactics on student plies are things the student CREATES — often good for the student.
- Tactics on opponent plies are threats the student will FACE — often bad for the student.
- Each piece is labeled with its color (e.g., "White B", "Black N").
- "hanging White B on b5" on a Black student's ply means the student attacks White's bishop.
- "hanging Black P on e5" on a White student's ply means the student left Black's pawn capturable.
- The piece COLOR creating a tactic determines who benefits. "fork by White N" benefits White; \
"skewer by Black Q" benefits Black. Use the piece color, not just the ply label.
- NEVER describe a student's own tactic as something the opponent exploits.

ACCURACY:
- Use the EXACT move notation shown in the analysis (e.g., "Be2" not "Bf2").
- If the analysis says the student "played: d4", say "d4" — do NOT say "captured on d4" \
unless the move notation includes "x" (e.g., "Nxe4" is a capture, "d4" is not).
- In chess notation, the letter BEFORE "x" is the piece that captures. \
"Bxf7" means a bishop captures on f7, NOT that a bishop is captured. \
"Bxd1" means a bishop captures whatever was on d1 (which could be a queen, rook, etc.).\
"""


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
        described_types.add("discovered_attack")  # always described (even if filtered to 0)
    if "checkmate" in new:
        described_types.add("checkmate")

    # Fallback: emit bare motif name for any new motifs without structured detail
    for motif in sorted(new - described_types):
        descriptions.append(motif)

    return descriptions


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


_OPPONENT_SYSTEM_PROMPT = """\
You are a chess teacher selecting a move for the opponent (computer) side.
Your goal is to choose the move that creates the most instructive position \
for the student to learn from.

Rules:
- You MUST pick one of the provided candidate moves.
- Prefer moves that create clear tactical or positional themes.
- In the opening, prefer principled development moves.
- In the middlegame, prefer moves that create instructive imbalances.
- Avoid moves that are too tricky or engine-like for the student's level.
- Respond with ONLY valid JSON: {"selected_move": "<SAN>", "reason": "..."}
- Keep the reason under 30 words.\
"""


def _build_opponent_prompt(ctx: OpponentMoveContext) -> str:
    """Build the user-message content for opponent move selection."""
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


class ChessTeacher:
    """Generates natural-language coaching via a local Ollama LLM."""

    def __init__(
        self,
        ollama_url: str = "https://ollama.st5ve.com",
        model: str = "qwen2.5:14b",
        timeout: float = 15.0,
    ):
        self._url = ollama_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def explain_move(self, prompt: str) -> str | None:
        """Ask the LLM to explain a move given a grounded prompt.

        The prompt should be produced by format_coaching_prompt() and
        contains only pre-computed facts for the LLM to reference.
        Returns None on any failure.
        """
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        return await self._chat(messages)

    async def select_teaching_move(
        self, context: OpponentMoveContext
    ) -> tuple[str, str] | None:
        """Ask the LLM to pick a pedagogically valuable move.

        Returns (selected_san, reason) or None on failure.
        """
        messages = [
            {"role": "system", "content": _OPPONENT_SYSTEM_PROMPT},
            {"role": "user", "content": _build_opponent_prompt(context)},
        ]
        text = await self._chat(messages, timeout=10.0)
        if text is None:
            return None
        return _parse_move_selection(text)

    async def _chat(
        self, messages: list[dict], timeout: float | None = None
    ) -> str | None:
        """POST to Ollama /api/chat and return the assistant content."""
        t = timeout if timeout is not None else self._timeout
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=t) as client:
                resp = await client.post(
                    f"{self._url}/api/chat", json=payload
                )
                resp.raise_for_status()
                data = resp.json()
                return data["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return None


def _parse_move_selection(text: str) -> tuple[str, str] | None:
    """Parse LLM JSON response for move selection.

    Tries json.loads first, then regex fallback for messy output.
    """
    # Try clean JSON parse
    try:
        data = json.loads(text)
        move = data["selected_move"]
        reason = data.get("reason", "")
        if isinstance(move, str) and move.strip():
            return move.strip(), str(reason)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Regex fallback: look for "selected_move": "Nf3" pattern
    m = re.search(r'"selected_move"\s*:\s*"([^"]+)"', text)
    if m:
        move = m.group(1).strip()
        r = re.search(r'"reason"\s*:\s*"([^"]*)"', text)
        reason = r.group(1) if r else ""
        return move, reason

    return None
