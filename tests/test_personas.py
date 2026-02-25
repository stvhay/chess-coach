"""Tests for the persona registry."""

from server.prompts.personas import (
    DEFAULT_PERSONA_NAME,
    PERSONAS,
    all_personas,
    get_persona,
)


class TestPersonaRegistry:
    """Verify persona registry structure and lookup."""

    def test_fourteen_personas(self):
        """Registry contains exactly 14 personas."""
        assert len(PERSONAS) == 14

    def test_all_personas_count(self):
        """all_personas() returns the same 14."""
        assert len(all_personas()) == 14

    def test_no_duplicate_names(self):
        """No duplicate persona names."""
        names = [p.name for p in all_personas()]
        assert len(names) == len(set(names))

    def test_default_is_anna_cramling(self):
        assert DEFAULT_PERSONA_NAME == "Anna Cramling"
        assert "Anna Cramling" in PERSONAS

    def test_all_have_required_fields(self):
        """Every persona has non-empty name, display_label, and persona_block."""
        for p in all_personas():
            assert p.name, f"Persona missing name: {p}"
            assert p.display_label, f"Persona missing display_label: {p}"
            assert p.persona_block, f"Persona missing persona_block: {p}"
            assert len(p.persona_block) > 20, (
                f"Persona block too short for {p.name}: {p.persona_block!r}"
            )

    def test_get_persona_known(self):
        """get_persona returns the correct persona for a known name."""
        anna = get_persona("Anna Cramling")
        assert anna.name == "Anna Cramling"

        hikaru = get_persona("Hikaru")
        assert hikaru.name == "Hikaru"

    def test_get_persona_fallback_unknown(self):
        """Unknown names fall back to the default."""
        p = get_persona("nonexistent coach")
        assert p.name == DEFAULT_PERSONA_NAME

    def test_get_persona_fallback_old_default(self):
        """Old localStorage value 'a chess coach' falls back gracefully."""
        p = get_persona("a chess coach")
        assert p.name == DEFAULT_PERSONA_NAME

    def test_display_order_matches_list(self):
        """all_personas() preserves insertion order."""
        personas = all_personas()
        assert personas[0].name == "Anna Cramling"
        assert personas[-1].name == "Faustino Oro"

    def test_expected_persona_names(self):
        """All 14 expected names are present."""
        expected = {
            "Anna Cramling", "Daniel Naroditsky", "GothamChess",
            "GM Ben Finegold", "Hikaru", "Judit Polgar", "Magnus Carlsen",
            "Vishy Anand", "Garry Kasparov", "Mikhail Botvinnik",
            "Paul Morphy", "Mikhail Tal", "Jose Raul Capablanca",
            "Faustino Oro",
        }
        assert set(PERSONAS.keys()) == expected
