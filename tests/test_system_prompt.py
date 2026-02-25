"""Tests for the composable system prompt builder."""

from server.prompts.personas import PERSONAS, get_persona
from server.prompts.system import (
    COACHING_SYSTEM_PROMPT,
    build_coaching_system_prompt,
)


class TestBaseRules:
    """Base coaching rules always appear regardless of options."""

    def test_anti_hallucination_rule(self):
        prompt = build_coaching_system_prompt(persona_block="Test persona.")
        assert "ONLY the analysis data provided" in prompt

    def test_markdown_policy(self):
        prompt = build_coaching_system_prompt(persona_block="Test persona.")
        # Allow bold, but not other markdown
        assert "**bold**" in prompt or "may use **bold**" in prompt
        assert "Do not use other markdown formatting" in prompt

    def test_stay_in_character_rule(self):
        prompt = build_coaching_system_prompt(persona_block="Test persona.")
        assert "Stay in character" in prompt

    def test_address_as_you(self):
        prompt = build_coaching_system_prompt(persona_block="Test persona.")
        assert 'Address the student as "you."' in prompt

    def test_natural_language_rule(self):
        prompt = build_coaching_system_prompt(persona_block="Test persona.")
        assert "natural language" in prompt


class TestPersonaInjection:
    """Persona block is correctly injected."""

    def test_persona_block_appears(self):
        block = "You speak as Test Coach. Very unique text here."
        prompt = build_coaching_system_prompt(persona_block=block)
        assert block in prompt

    def test_real_persona_injected(self):
        anna = get_persona("Anna Cramling")
        prompt = build_coaching_system_prompt(persona_block=anna.persona_block)
        assert "Anna Cramling" in prompt

    def test_all_personas_produce_valid_prompts(self):
        for name, persona in PERSONAS.items():
            prompt = build_coaching_system_prompt(persona_block=persona.persona_block)
            assert persona.persona_block in prompt, f"Persona block missing for {name}"
            assert "ONLY the analysis data" in prompt, f"Base rules missing for {name}"


class TestQualityGuidance:
    """Move quality guidance present/absent based on parameter."""

    def test_quality_none_omitted(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", move_quality=None,
        )
        assert "Move quality" not in prompt
        assert "blunder" not in prompt.lower().split("your persona")[0]

    def test_quality_blunder_present(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", move_quality="blunder",
        )
        assert "serious error" in prompt

    def test_quality_good_present(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", move_quality="good",
        )
        assert "played well" in prompt

    def test_quality_inaccuracy_present(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", move_quality="inaccuracy",
        )
        assert "slightly suboptimal" in prompt

    def test_quality_mistake_present(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", move_quality="mistake",
        )
        assert "learning opportunity" in prompt

    def test_quality_brilliant_present(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", move_quality="brilliant",
        )
        assert "exceptional" in prompt

    def test_unknown_quality_omitted(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", move_quality="unknown_value",
        )
        assert "Move quality" not in prompt


class TestEloGuidance:
    """ELO guidance present/absent based on parameter."""

    def test_elo_none_omitted(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", elo_profile=None,
        )
        assert "Student level" not in prompt

    def test_elo_beginner(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", elo_profile="beginner",
        )
        assert "beginner" in prompt.lower()
        assert "simple vocabulary" in prompt.lower()

    def test_elo_intermediate(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", elo_profile="intermediate",
        )
        assert "intermediate" in prompt.lower()

    def test_elo_advancing(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", elo_profile="advancing",
        )
        assert "advancing" in prompt.lower()

    def test_elo_club(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", elo_profile="club",
        )
        assert "club" in prompt.lower()

    def test_elo_competitive(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", elo_profile="competitive",
        )
        assert "competitive" in prompt.lower()

    def test_unknown_elo_omitted(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", elo_profile="grandmaster",
        )
        assert "Student level" not in prompt


class TestVerbosityGuidance:
    """Verbosity guidance includes correct word counts."""

    def test_terse_word_count(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", verbosity="terse",
        )
        assert "25-75 words" in prompt

    def test_normal_word_count(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", verbosity="normal",
        )
        assert "50-150 words" in prompt

    def test_verbose_word_count(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", verbosity="verbose",
        )
        assert "150-400 words" in prompt

    def test_unknown_verbosity_defaults_to_normal(self):
        prompt = build_coaching_system_prompt(
            persona_block="Test.", verbosity="unknown",
        )
        assert "50-150 words" in prompt


class TestBackwardCompat:
    """COACHING_SYSTEM_PROMPT constant still exists for backward compat."""

    def test_constant_exists(self):
        assert isinstance(COACHING_SYSTEM_PROMPT, str)

    def test_constant_has_base_rules(self):
        assert "ONLY the analysis data" in COACHING_SYSTEM_PROMPT

    def test_constant_has_default_persona(self):
        assert "Anna Cramling" in COACHING_SYSTEM_PROMPT

    def test_constant_has_verbosity(self):
        # Default verbosity is "normal"
        assert "50-150 words" in COACHING_SYSTEM_PROMPT


class TestComposition:
    """Full composition with all sections."""

    def test_all_sections_present(self):
        prompt = build_coaching_system_prompt(
            persona_block="Unique persona text here.",
            move_quality="mistake",
            elo_profile="club",
            verbosity="verbose",
        )
        # Base rules
        assert "ONLY the analysis data" in prompt
        # Persona
        assert "Unique persona text here." in prompt
        # Quality
        assert "learning opportunity" in prompt
        # ELO
        assert "club level" in prompt
        # Verbosity
        assert "150-400 words" in prompt

    def test_sections_in_order(self):
        prompt = build_coaching_system_prompt(
            persona_block="PERSONA_MARKER",
            move_quality="blunder",
            elo_profile="beginner",
            verbosity="terse",
        )
        persona_pos = prompt.index("PERSONA_MARKER")
        quality_pos = prompt.index("serious error")
        elo_pos = prompt.index("beginner")
        verbosity_pos = prompt.index("25-75 words")
        assert persona_pos < quality_pos < elo_pos < verbosity_pos
