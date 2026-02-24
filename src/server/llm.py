"""LLM orchestrator for chess coaching.

Sends structured move assessment data to an OpenAI-compatible API
(Ollama, OpenRouter, litellm, etc.) and returns natural-language
coaching messages.  Falls back gracefully (returns None) when the
LLM is unreachable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from server.prompts import (
    COACHING_SYSTEM_PROMPT,
    OPPONENT_SYSTEM_PROMPT,
    build_opponent_prompt,
)


@dataclass
class OpponentMoveContext:
    """Everything the LLM needs to select a teaching move."""
    fen: str
    game_phase: str
    position_summary: str
    candidates: list[dict]   # [{san, uci, score_cp}, ...]
    player_color: str


class ChessTeacher:
    """Generates natural-language coaching via an OpenAI-compatible LLM API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    async def explain_move(self, prompt: str) -> str | None:
        """Ask the LLM to explain a move given a grounded prompt.

        The prompt should be produced by serialize_report() and
        contains only pre-computed facts for the LLM to reference.
        Returns None on any failure.
        """
        messages = [
            {"role": "system", "content": COACHING_SYSTEM_PROMPT},
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
            {"role": "system", "content": OPPONENT_SYSTEM_PROMPT},
            {"role": "user", "content": build_opponent_prompt(context)},
        ]
        text = await self._chat(messages, timeout=10.0)
        if text is None:
            return None
        return _parse_move_selection(text)

    async def _chat(
        self, messages: list[dict], timeout: float | None = None
    ) -> str | None:
        """POST to OpenAI-compatible /v1/chat/completions endpoint."""
        t = timeout if timeout is not None else self._timeout
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self._model,
            "messages": messages,
        }
        try:
            async with httpx.AsyncClient(timeout=t) as client:
                resp = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError):
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
