"""LLM orchestrator for chess coaching.

Sends structured move assessment data to a local Ollama instance and
returns natural-language coaching messages.  Falls back gracefully
(returns None) when the LLM is unreachable.
"""

from __future__ import annotations

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
    lines.append(
        "Explain this move to the student. "
        "If it was good, praise it briefly. "
        "If it was a mistake, explain what went wrong and why the best move is better."
    )
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

    async def _chat(self, messages: list[dict]) -> str | None:
        """POST to Ollama /api/chat and return the assistant content."""
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._url}/api/chat", json=payload
                )
                resp.raise_for_status()
                data = resp.json()
                return data["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return None
