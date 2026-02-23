"""Prompt formatting helpers for opponent move selection.

The coaching prompt pipeline has moved to report.py and descriptions.py.
This module retains only the opponent prompt builder.
"""

from __future__ import annotations


def build_opponent_prompt(ctx) -> str:
    """Build the user-message content for opponent move selection.

    Accepts an OpponentMoveContext (imported at call site to avoid
    circular imports with llm.py).
    """
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
