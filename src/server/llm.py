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


@dataclass
class MoveContext:
    """Everything the LLM needs to explain a move."""
    fen_before: str
    fen_after: str
    player_move_san: str
    best_move_san: str
    quality: str          # "blunder" / "mistake" / "inaccuracy" / "brilliant"
    cp_loss: int
    tactics_summary: str
    player_color: str     # "White" or "Black"
    rag_context: str = ""


@dataclass
class OpponentMoveContext:
    """Everything the LLM needs to select a teaching move."""
    fen: str
    game_phase: str
    position_summary: str
    candidates: list[dict]   # [{san, uci, score_cp}, ...]
    player_color: str


_SYSTEM_PROMPT = """\
You are a chess coach talking to an intermediate player.
Be concise: 2-3 sentences maximum.
Be encouraging, not condescending.
Reference specific pieces and squares.
Mention tactical themes (forks, pins, hanging pieces) when relevant.
Never mention centipawn values — translate to concepts \
("significant material", "roughly a pawn's worth", etc.).
Do not use markdown formatting.\
"""


def _build_user_prompt(ctx: MoveContext) -> str:
    """Build the user-message content from structured assessment data."""
    lines = [
        f"Position (before move): {ctx.fen_before}",
        f"Player ({ctx.player_color}) played: {ctx.player_move_san}",
        f"Engine's best move was: {ctx.best_move_san}",
        f"Move quality: {ctx.quality}",
        f"Material lost: approximately {ctx.cp_loss / 100:.1f} pawns",
    ]
    if ctx.tactics_summary:
        lines.append(f"Tactical details: {ctx.tactics_summary}")
    if ctx.rag_context:
        lines.append(f"Relevant chess knowledge:\n{ctx.rag_context}")
    lines.append(
        "Explain this move to the student. "
        "If it was good, praise it briefly. "
        "If it was a mistake, explain what went wrong and why the best move is better."
    )
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

    async def explain_move(self, context: MoveContext) -> str | None:
        """Ask the LLM to explain a move.  Returns None on any failure."""
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(context)},
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
