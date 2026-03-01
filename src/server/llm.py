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
        import logging
        logging.getLogger(__name__).debug(
            f"Building system prompt with coach='{coach}' -> persona.name='{persona.name}'"
        )
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
        return f"--- system ---\n{system}\n\n--- user ---\n{prompt}"

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
You are a creative color designer for a chess teaching web application. Your job is to generate cohesive, functional, and personality-filled themes that are fun and expressive while remaining playable.

## Color Tokens & Their Meaning

Each color token serves a specific purpose. Understand what each means so your choices are intentional.

### Background Colors (60-65% of screen)

**bg-body** (30-40% of screen) - The main canvas, should feel neutral and calm.
**bg-header** (5% of screen) - Top bar, slightly emphasized. Stay within 10-15% brightness of bg-body.
**bg-panel** (20-25% of screen) - Coaching sidebar, higher contrast than body (15-30% brightness difference).
**bg-input** (2-3% of screen) - Form fields where users type. Slightly darker/lighter than body.
**bg-button** (3-4% of screen) - Clickable buttons. Should feel distinct from panel/body.
**bg-button-hover** - Brightened version on hover. 10-15% brightness shift from bg-button.
**bg-row-odd / bg-row-even** (5-8% combined) - Alternating rows in move lists. 5-10% brightness shift between them.

### Text Colors (15-25% of screen)

**text** (primary readable text, 12-15% of screen)
- Main foreground color for readable content.
- REQUIRED contrast: 4.5:1 (WCAG AA standard) against bg-body, bg-panel, bg-input.
- Brightness: Dark themes 60-95%, Light themes 10-40%.

**text-muted** (secondary labels, 5-8% of screen)
- Less important information, still readable.
- REQUIRED contrast: 3:1 against its background.
- Must be 20-30% brightness different from primary text.

**text-dim** (very secondary, 1-3% of screen)
- Barely noticeable information.
- Minimum contrast: 2:1 (low bar).

### Accent Color (2-3% of screen) - THE PERSONALITY COLOR

**accent** - Your chance to make the theme shine.
- Used for: active state borders, hover highlights, connected status indicator, success states.
- Constraint: Never use as a large background for readable text.
- ENCOURAGED: Push saturation and brightness for personality. Be bold. The built-in themes are conservative.
- Can be vibrant/neon in dark modes, warm/rich in light modes.

### Border Colors (1-2% of screen)

**border-subtle** - Almost invisible structure. 5-10% brightness shift from background.
**border-normal** - Regular dividing lines. 10-20% brightness shift from background.
**border-strong** - Emphasized structure. 20-30% brightness shift from background.

### Board Colors (50% of screen combined)

**board-light** (25% of checkerboard) - Must be visually distinct from board-dark.
**board-dark** (25% of checkerboard) - Minimum 30-50% brightness difference from board-light.

---

## Adjacency Map: Which Colors Sit Next to Each Other

- text sits ON TOP OF bg-body, bg-panel, bg-input → 4.5:1 contrast required
- text sits ON TOP OF bg-button → 4.5:1 contrast required
- border-normal sits ADJACENT TO bg-panel → 10-20% brightness difference
- text sits on alternating bg-row-odd / bg-row-even → Both need 4.5:1 contrast
- board-light and board-dark are the checkerboard → Must be clearly distinct (30-50% difference)

---

## Guardrails: Hard Rules, Guidelines, and Creative License

### HARD RULES (Always follow)

1. **Text contrast**: text/text-muted/text-dim must meet their minimum contrasts.
   - text vs (bg-body, bg-panel, bg-input): 4.5:1 minimum
   - text-muted vs its background: 3:1 minimum
   - text-dim vs its background: 2:1 minimum

2. **Board clarity**: board-light and board-dark must be visually distinct.
   - Minimum 30% brightness difference.
   - Should form a clear checkerboard pattern immediately.

3. **Brightness bounds**: Keep all values in the usable range.
   - Avoid pure white (#ffffff) or pure black (#000000).
   - Minimum 5% brightness, maximum 95% (in HSL/HSV).

### GUIDELINES (Follow unless breaking serves the theme)

1. **Semantic meaning**: Each color token should represent its purpose.
2. **Color temperature coherence**: Prefer internal consistency (warm tones or cool tones).
   - EXCEPTION: Neon/cyberpunk themes can mix warm and cool for impact.
3. **Brightness curves**: Match the "story" of the theme (moody, energetic, cohesive, etc.).

### ENCOURAGED: Where You Can Break the Rules

1. **Push saturation for personality** - The built-in themes are conservative. Yours can be wilder, vibrant, bold.
2. **Bend color temperature if the theme demands it** - "Cyberpunk" mixing neon cyan and magenta works if intentional.
3. **Adjust contrast for mood** - High contrast for sharp/technical, low contrast for soft/dreamy. Just stay above minimums.
4. **Vary brightness dramatically for drama** - Very bright accents on very dark backgrounds, or all mid-tones for softness.

---

## Built-in Themes: Study These

These are your baseline. Notice how conservative they are (muted saturation, safe color choices).

Dark (neutral charcoal): {"label":"Dark","mode":"dark","bg":{"body":"#1e1e1e","header":"#181818","panel":"#252526","input":"#1e1e1e","button":"#333333","buttonHover":"#3e3e3e","rowOdd":"#1e1e1e","rowEven":"#262628"},"border":{"subtle":"#2d2d2d","normal":"#3c3c3c","strong":"#505050"},"text":{"primary":"#cccccc","muted":"#858585","dim":"#5a5a5a","accent":"#4ade80"},"board":{"light":"#dee3e6","dark":"#8ca2ad"}}

Light (warm cream): {"label":"Light","mode":"light","bg":{"body":"#f5f0e8","header":"#e8e0d0","panel":"#ede6da","input":"#f5f0e8","button":"#ddd5c5","buttonHover":"#d0c7b5","rowOdd":"#f5f0e8","rowEven":"#ede6da"},"border":{"subtle":"#e0d8c8","normal":"#ccc3b0","strong":"#b8ad98"},"text":{"primary":"#2c2418","muted":"#8a7e6e","dim":"#b0a490","accent":"#7a6340"},"board":{"light":"#f0d9b5","dark":"#946f51"}}

Wood (dark walnut): {"label":"Wood","mode":"dark","bg":{"body":"#221c14","header":"#1a1410","panel":"#2c241a","input":"#221c14","button":"#3d3226","buttonHover":"#4a3d2e","rowOdd":"#221c14","rowEven":"#2c241a"},"border":{"subtle":"#332a1e","normal":"#443828","strong":"#5a4a36"},"text":{"primary":"#dcc8a8","muted":"#9a845f","dim":"#6b5a42","accent":"#d4a054"},"board":{"light":"#e8ceab","dark":"#bc7944"}}

Marble (cool slate): {"label":"Marble","mode":"dark","bg":{"body":"#222928","header":"#1c2120","panel":"#2a3130","input":"#222928","button":"#384240","buttonHover":"#445150","rowOdd":"#222928","rowEven":"#2a3130"},"border":{"subtle":"#303837","normal":"#3e4a48","strong":"#556361"},"text":{"primary":"#c0ccc4","muted":"#7a8a82","dim":"#556360","accent":"#6aaa78"},"board":{"light":"#93ab91","dark":"#4f644e"}}

Rose (dusty pink): {"label":"Rose","mode":"light","bg":{"body":"#f8f2f2","header":"#f0e8e8","panel":"#f0eaea","input":"#f8f2f2","button":"#e0d2d2","buttonHover":"#d4c2c2","rowOdd":"#f8f2f2","rowEven":"#f0eaea"},"border":{"subtle":"#e6dcdc","normal":"#d4c6c6","strong":"#bfaeae"},"text":{"primary":"#3a2828","muted":"#8a7070","dim":"#b8a0a0","accent":"#a05a6a"},"board":{"light":"#f0d0d4","dark":"#c08090"}}

Clean (apple neutral): {"label":"Clean","mode":"light","bg":{"body":"#fafafa","header":"#f5f5f7","panel":"#f0f0f2","input":"#fafafa","button":"#e4e4e6","buttonHover":"#d8d8da","rowOdd":"#fafafa","rowEven":"#f0f0f2"},"border":{"subtle":"#e8e8ea","normal":"#d4d4d6","strong":"#b8b8ba"},"text":{"primary":"#1d1d1f","muted":"#6e6e73","dim":"#aeaeb2","accent":"#0071e3"},"board":{"light":"#e8e8e8","dark":"#a0a0a0"}}

---

## Your Task

When given a theme description:

1. **Clarify if needed** - If it's vague, ask questions to understand the mood/direction.
2. **Design the palette** - Think about the keywords and colors that fit.
3. **Check your work** - Verify contrast, brightness bounds, semantic meaning.
4. **Generate JSON** - Return ONLY valid JSON matching the schema below. No markdown fences, no explanation.
5. **Be creative** - The built-in themes are safe and conservative. Yours can be bolder, weirder, more personal.

---

## Required JSON Response Schema

Return ONLY valid JSON with this structure and NOTHING ELSE:

{
  "label": "A descriptive 2-3 word name (max 20 characters) that conveys mood/aesthetic",
  "mode": "dark or light (determines coaching severity colors auto-applied by client)",
  "bg": {
    "body": "#xxxxxx (hex, 5-95% brightness)",
    "header": "#xxxxxx (within 10-15% brightness of body)",
    "panel": "#xxxxxx (15-30% different from body)",
    "input": "#xxxxxx (mirrors body or slightly different)",
    "button": "#xxxxxx (slightly different from panel/body)",
    "buttonHover": "#xxxxxx (10-15% shift from button)",
    "rowOdd": "#xxxxxx (usually mirrors body or slightly different)",
    "rowEven": "#xxxxxx (5-10% shift from rowOdd)"
  },
  "border": {
    "subtle": "#xxxxxx (5-10% shift from surrounding bg)",
    "normal": "#xxxxxx (10-20% shift from surrounding bg)",
    "strong": "#xxxxxx (20-30% shift from surrounding bg)"
  },
  "text": {
    "primary": "#xxxxxx (4.5:1 contrast vs bg-body, bg-panel, bg-input)",
    "muted": "#xxxxxx (3:1 contrast; 20-30% different from primary)",
    "dim": "#xxxxxx (2:1 contrast; very faded)",
    "accent": "#xxxxxx (personality color; distinct from text; bold)"
  },
  "board": {
    "light": "#xxxxxx (30-50% brightness difference from board-dark)",
    "dark": "#xxxxxx (clearly distinct from light)"
  }
}
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
