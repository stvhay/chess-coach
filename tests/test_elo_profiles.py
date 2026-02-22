from server.elo_profiles import (
    ELO_PROFILES,
    DEFAULT_PROFILE,
    EloProfile,
    get_profile,
)


def test_all_profiles_are_elo_profile_instances():
    for name, profile in ELO_PROFILES.items():
        assert isinstance(profile, EloProfile)
        assert profile.name == name


def test_default_profile_exists():
    assert DEFAULT_PROFILE in ELO_PROFILES


def test_get_profile_known():
    p = get_profile("beginner")
    assert p.name == "beginner"
    assert p.elo_range == "600-800"


def test_get_profile_unknown_returns_default():
    p = get_profile("grandmaster")
    assert p.name == DEFAULT_PROFILE


def test_profile_depths_increase_with_level():
    ordered = ["beginner", "intermediate", "advancing", "club", "competitive"]
    profiles = [ELO_PROFILES[n] for n in ordered]
    for i in range(len(profiles) - 1):
        assert profiles[i].validate_depth <= profiles[i + 1].validate_depth


def test_profile_thresholds_decrease_with_level():
    ordered = ["beginner", "intermediate", "advancing", "club", "competitive"]
    profiles = [ELO_PROFILES[n] for n in ordered]
    for i in range(len(profiles) - 1):
        assert profiles[i].cp_threshold >= profiles[i + 1].cp_threshold


def test_all_profiles_have_positive_values():
    for profile in ELO_PROFILES.values():
        assert profile.screen_depth > 0
        assert profile.screen_breadth > 0
        assert profile.validate_depth > 0
        assert profile.validate_breadth > 0
        assert profile.max_concept_depth > 0
        assert profile.cp_threshold > 0
