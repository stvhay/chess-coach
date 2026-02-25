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
    OPPONENT_SYSTEM_PROMPT,
    build_coaching_system_prompt,
    build_opponent_prompt,
    get_persona,
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

    def _build_system_prompt(
        self,
        coach: str,
        verbosity: str,
        move_quality: str | None = None,
        elo_profile: str | None = None,
    ) -> str:
        """Build system prompt with persona, quality, ELO, and verbosity."""
        persona = get_persona(coach)
        return build_coaching_system_prompt(
            persona_block=persona.persona_block,
            move_quality=move_quality,
            elo_profile=elo_profile,
            verbosity=verbosity,
        )

    async def explain_move(
        self,
        prompt: str,
        coach: str = "Anna Cramling",
        verbosity: str = "normal",
        move_quality: str | None = None,
        elo_profile: str | None = None,
    ) -> str | None:
        """Ask the LLM to explain a move given a grounded prompt.

        The prompt should be produced by serialize_report() and
        contains only pre-computed facts for the LLM to reference.
        Returns None on any failure.
        """
        system = self._build_system_prompt(
            coach, verbosity, move_quality=move_quality, elo_profile=elo_profile,
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        return await self._chat(messages)

    def build_debug_prompt(
        self,
        prompt: str,
        coach: str = "Anna Cramling",
        verbosity: str = "normal",
        move_quality: str | None = None,
        elo_profile: str | None = None,
    ) -> str:
        """Build the full prompt (system + user) for debugging.

        Returns a formatted string showing both the system and user messages
        that would be sent to the LLM.
        """
        system = self._build_system_prompt(
            coach, verbosity, move_quality=move_quality, elo_profile=elo_profile,
        )
        return f"SYSTEM:\n{system}\n\nUSER:\n{prompt}"

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

    async def generate_theme(self, description: str) -> dict | None:
        """Ask the LLM to generate a color theme from a description.

        Returns parsed JSON dict or None on failure.
        """
        messages = [
            {"role": "system", "content": _THEME_SYSTEM_PROMPT},
            {"role": "user", "content": description},
        ]
        text = await self._chat(messages, timeout=20.0)
        if text is None:
            return None
        return _parse_theme_response(text)

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


_THEME_SYSTEM_PROMPT = """\
You are a color theme designer for a chess teaching application. Given a description, \
generate a cohesive color palette.

Return ONLY valid JSON matching this exact schema — no markdown, no explanation:

{
  "label": "<one word name>",
  "mode": "<dark or light>",
  "bg": {
    "body": "<hex>", "header": "<hex>", "panel": "<hex>", "input": "<hex>",
    "button": "<hex>", "buttonHover": "<hex>", "rowOdd": "<hex>", "rowEven": "<hex>"
  },
  "border": { "subtle": "<hex>", "normal": "<hex>", "strong": "<hex>" },
  "text": { "primary": "<hex>", "muted": "<hex>", "dim": "<hex>", "accent": "<hex>" },
  "board": { "light": "<hex>", "dark": "<hex>" }
}

Rules:
- "mode": "dark" if body background luminance < 50%, "light" otherwise
- "label": one creative word that captures the theme's mood
- All values must be 7-character hex codes (#rrggbb)
- body is the main background; header/panel are slightly lighter or darker
- button and buttonHover must be distinguishable from panel
- text.primary must have >= 4.5:1 contrast ratio against bg.body
- text.muted should be readable but subdued; text.dim is for low-priority info
- board.light and board.dark must have visible contrast (the chess squares)
- border.subtle < border.normal < border.strong in terms of visibility

Here are 6 examples of good themes:

Dark (neutral charcoal):
{"label":"Dark","mode":"dark","bg":{"body":"#1e1e1e","header":"#181818","panel":"#252526","input":"#1e1e1e","button":"#333333","buttonHover":"#3e3e3e","rowOdd":"#1e1e1e","rowEven":"#262628"},"border":{"subtle":"#2d2d2d","normal":"#3c3c3c","strong":"#505050"},"text":{"primary":"#cccccc","muted":"#858585","dim":"#5a5a5a","accent":"#4ade80"},"board":{"light":"#dee3e6","dark":"#8ca2ad"}}

Light (warm cream):
{"label":"Light","mode":"light","bg":{"body":"#f5f0e8","header":"#e8e0d0","panel":"#ede6da","input":"#f5f0e8","button":"#ddd5c5","buttonHover":"#d0c7b5","rowOdd":"#f5f0e8","rowEven":"#ede6da"},"border":{"subtle":"#e0d8c8","normal":"#ccc3b0","strong":"#b8ad98"},"text":{"primary":"#2c2418","muted":"#8a7e6e","dim":"#b0a490","accent":"#7a6340"},"board":{"light":"#f0d9b5","dark":"#946f51"}}

Wood (dark walnut):
{"label":"Wood","mode":"dark","bg":{"body":"#221c14","header":"#1a1410","panel":"#2c241a","input":"#221c14","button":"#3d3226","buttonHover":"#4a3d2e","rowOdd":"#221c14","rowEven":"#2c241a"},"border":{"subtle":"#332a1e","normal":"#443828","strong":"#5a4a36"},"text":{"primary":"#dcc8a8","muted":"#9a845f","dim":"#6b5a42","accent":"#d4a054"},"board":{"light":"#e8ceab","dark":"#bc7944"}}

Marble (cool slate):
{"label":"Marble","mode":"dark","bg":{"body":"#222928","header":"#1c2120","panel":"#2a3130","input":"#222928","button":"#384240","buttonHover":"#445150","rowOdd":"#222928","rowEven":"#2a3130"},"border":{"subtle":"#303837","normal":"#3e4a48","strong":"#556361"},"text":{"primary":"#c0ccc4","muted":"#7a8a82","dim":"#556360","accent":"#6aaa78"},"board":{"light":"#93ab91","dark":"#4f644e"}}

Rose (dusty pink):
{"label":"Rose","mode":"light","bg":{"body":"#f8f2f2","header":"#f0e8e8","panel":"#f0eaea","input":"#f8f2f2","button":"#e0d2d2","buttonHover":"#d4c2c2","rowOdd":"#f8f2f2","rowEven":"#f0eaea"},"border":{"subtle":"#e6dcdc","normal":"#d4c6c6","strong":"#bfaeae"},"text":{"primary":"#3a2828","muted":"#8a7070","dim":"#b8a0a0","accent":"#a05a6a"},"board":{"light":"#f0d0d4","dark":"#c08090"}}

Clean (apple neutral):
{"label":"Clean","mode":"light","bg":{"body":"#fafafa","header":"#f5f5f7","panel":"#f0f0f2","input":"#fafafa","button":"#e4e4e6","buttonHover":"#d8d8da","rowOdd":"#fafafa","rowEven":"#f0f0f2"},"border":{"subtle":"#e8e8ea","normal":"#d4d4d6","strong":"#b8b8ba"},"text":{"primary":"#1d1d1f","muted":"#6e6e73","dim":"#aeaeb2","accent":"#0071e3"},"board":{"light":"#e8e8e8","dark":"#a0a0a0"}}
"""


def _parse_theme_response(text: str) -> dict | None:
    """Parse LLM theme JSON response. Handles markdown fences."""
    # Strip markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (with optional language tag)
        cleaned = re.sub(r"^```\w*\n?", "", cleaned)
        # Remove closing fence
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON object from surrounding text
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    # Validate required structure
    required_keys = {"label", "mode", "bg", "border", "text", "board"}
    if not isinstance(data, dict) or not required_keys.issubset(data.keys()):
        return None
    if data.get("mode") not in ("dark", "light"):
        return None

    return data
