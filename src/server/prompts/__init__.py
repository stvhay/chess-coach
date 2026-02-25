"""Public API for prompt text and formatting."""

from server.prompts.personas import (
    DEFAULT_PERSONA_NAME,
    PERSONAS,
    Persona,
    all_personas,
    get_persona,
)
from server.prompts.system import (
    COACHING_SYSTEM_PROMPT,
    OPPONENT_SYSTEM_PROMPT,
    build_coaching_system_prompt,
)
from server.prompts.formatting import build_opponent_prompt
from server.report import serialize_report
