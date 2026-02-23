"""Public API for prompt text and formatting."""

from server.prompts.system import COACHING_SYSTEM_PROMPT, OPPONENT_SYSTEM_PROMPT
from server.prompts.formatting import build_opponent_prompt
from server.report import serialize_report
