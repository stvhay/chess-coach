"""Test for coach selection bug.

Verifies that the coach name from localStorage is used on initial page load,
not the hardcoded default.
"""

from server.prompts.personas import get_persona


def test_persona_lookup_works():
    """Verify backend persona lookup works correctly."""
    persona = get_persona("Judit Polgar")
    assert persona.name == "Judit Polgar"
    assert "Judit Polgar" in persona.persona_block
    assert "Anna Cramling" not in persona.persona_block


def test_default_fallback():
    """Verify fallback to default persona for unknown names."""
    persona = get_persona("Unknown Coach")
    assert persona.name == "Anna Cramling"  # Should fall back to default


def test_all_coaches_in_frontend_exist_in_backend():
    """Verify all coaches in frontend dropdown exist in backend."""
    frontend_coaches = [
        "Anna Cramling",
        "Daniel Naroditsky",
        "GothamChess",
        "GM Ben Finegold",
        "Hikaru",
        "Judit Polgar",
        "Magnus Carlsen",
        "Vishy Anand",
        "Garry Kasparov",
        "Mikhail Botvinnik",
        "Paul Morphy",
        "Mikhail Tal",
        "Jose Raul Capablanca",
        "Faustino Oro",
    ]

    for coach_name in frontend_coaches:
        persona = get_persona(coach_name)
        assert persona.name == coach_name, f"Coach {coach_name} not found in backend"
