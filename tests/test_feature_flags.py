"""Tests for feature flags and TacticValue extension fields."""

from server.config_flags import is_chain_detection_enabled, is_tier2_chains_enabled
from server.analysis.tactics.types import TacticValue


# ---------------------------------------------------------------------------
# Feature flag tests
# ---------------------------------------------------------------------------


class TestChainDetectionFlag:
    def test_default_disabled(self, monkeypatch):
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_CHAINING", raising=False)
        assert is_chain_detection_enabled() is False

    def test_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        assert is_chain_detection_enabled() is True

    def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "0")
        assert is_chain_detection_enabled() is False


class TestTier2Flag:
    def test_tier2_requires_tier1(self, monkeypatch):
        """Tier 2 is only enabled when Tier 1 is also enabled."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_CHAINING", raising=False)
        assert is_tier2_chains_enabled() is False

    def test_tier2_enabled_when_both_set(self, monkeypatch):
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        assert is_tier2_chains_enabled() is True

    def test_tier2_disabled_when_tier1_only(self, monkeypatch):
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", raising=False)
        assert is_tier2_chains_enabled() is False


# ---------------------------------------------------------------------------
# TacticValue extension fields
# ---------------------------------------------------------------------------


class TestTacticValueExtensions:
    def test_defense_notes_default_empty(self):
        tv = TacticValue(material_delta=300, is_sound=True)
        assert tv.defense_notes == ""

    def test_related_motifs_default_empty(self):
        tv = TacticValue(material_delta=300, is_sound=True)
        assert tv.related_motifs == []

    def test_defense_notes_assigned(self):
        tv = TacticValue(material_delta=300, is_sound=True,
                         defense_notes="defender N on c6 pinned to e8")
        assert "pinned" in tv.defense_notes

    def test_related_motifs_assigned(self):
        tv = TacticValue(material_delta=300, is_sound=True,
                         related_motifs=["pin:b5-c6-e8"])
        assert len(tv.related_motifs) == 1
        assert tv.related_motifs[0] == "pin:b5-c6-e8"
