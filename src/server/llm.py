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
- Do NOT invent or guess tactical themes, piece locations, or consequences.
- Do NOT mention evaluation numbers or centipawn values.
- If the move classification is "good", affirm the student's choice. Do NOT suggest \
alternatives are better. You may briefly mention other options exist without recommending them.
- If the student's move is a blunder or mistake, clearly explain what was wrong and \
what the stronger alternative achieves using ONLY the listed annotations.
- Do not use markdown formatting.\
"""


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
            descriptions.append(f"fork by {fork.forking_piece} on {fork.forking_square} targeting {targets}")

    if "pin" in new:
        for pin in tactics.pins:
            descriptions.append(
                f"pin: {pin.pinned_piece} on {pin.pinned_square} pinned by "
                f"{pin.pinner_piece} on {pin.pinner_square} to {pin.pinned_to}"
            )

    if "skewer" in new:
        for skewer in tactics.skewers:
            descriptions.append(
                f"skewer by {skewer.attacker_piece} on {skewer.attacker_square}: "
                f"{skewer.front_piece} on {skewer.front_square}, "
                f"{skewer.behind_piece} on {skewer.behind_square}"
            )

    if "hanging_piece" in new:
        for hp in tactics.hanging:
            descriptions.append(f"hanging {hp.piece} on {hp.square}")

    if "discovered_attack" in new:
        significant = [da for da in tactics.discovered_attacks if _is_significant_discovery(da)]
        for da in significant[:3]:  # cap at 3 to prevent prompt bloat
            descriptions.append(
                f"discovered attack: {da.blocker_piece} on {da.blocker_square} "
                f"reveals {da.slider_piece} on {da.slider_square} targeting "
                f"{da.target_piece} on {da.target_square}"
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

        if ann.material_change != 0:
            mc = ann.material_change
            # Flip sign for black so positive = good for student
            if side_to_move_is_white is not None and not side_to_move_is_white:
                mc = -mc
            direction = "gains" if mc > 0 else "loses"
            parts.append(f"material {direction} {abs(ann.material_change)} cp")

        # Only emit this ply if there's something to say
        if parts:
            lines.append(f"  Ply {ann.ply + 1} ({ann.move_san}): {'; '.join(parts)}")
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
        lines.append(f"Student played: {pm.first_move_san}")
        if pm.pv_san and len(pm.pv_san) > 1:
            lines.append(f"  Likely continuation: {' '.join(pm.pv_san[1:])}")
        ply_lines = _format_ply_annotations(pm.annotations, student_is_white)
        if ply_lines:
            lines.extend(ply_lines)
        else:
            lines.append("  No notable tactics in this line.")
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
        lines.append(f"{label}: {alt.first_move_san}")
        if alt.pv_san and len(alt.pv_san) > 1:
            lines.append(f"  Likely continuation: {' '.join(alt.pv_san[1:])}")
        ply_lines = _format_ply_annotations(alt.annotations, student_is_white)
        if ply_lines:
            lines.extend(ply_lines)
        else:
            lines.append("  No notable tactics in this line.")
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
