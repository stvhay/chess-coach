"""Tests for Tier 2 chain detection and rendering.

Covers:
- Overload->hanging chain detection with flag on/off
- CapturableDefender->hanging chain detection with flag on/off
- Merged rendering and hanging suppression
- rendered_keys tracking
- Preservation of unrelated motifs
"""

import time

from server.analysis.tactics.types import (
    CapturableDefender,
    HangingPiece,
    OverloadedPiece,
    TacticValue,
    TacticalMotifs,
)
from server.motifs import (
    RenderContext,
    _detect_overload_hanging_chains,
    _detect_capturable_defender_hanging_chains,
    render_motifs,
)


# --- Helpers ---

def _ctx(student_is_white=True) -> RenderContext:
    return RenderContext(
        student_is_white=student_is_white,
        player_color="White" if student_is_white else "Black",
    )


def _make_overload_hanging_tactics() -> TacticalMotifs:
    """Overloaded Nd4 defends c6 and e6; e6 bishop is hanging."""
    overloaded = OverloadedPiece(
        square="d4", piece="n",
        defended_squares=["c6", "e6"],
        color="black",
        value=TacticValue(material_delta=300, is_sound=True, source="heuristic"),
    )
    hanging = HangingPiece(
        square="e6", piece="b", attacker_squares=["f5"],
        color="black", can_retreat=False,
        value=TacticValue(material_delta=300, is_sound=True),
    )
    return TacticalMotifs(overloaded_pieces=[overloaded], hanging=[hanging])


def _make_cd_hanging_tactics() -> TacticalMotifs:
    """CapturableDefender Nd4 defends Be6; Be6 also detected as hanging."""
    cd = CapturableDefender(
        defender_square="d4", defender_piece="n",
        charge_square="e6", charge_piece="b",
        attacker_square="c2", color="black",
        value=TacticValue(material_delta=600, is_sound=True),
    )
    hanging = HangingPiece(
        square="e6", piece="b", attacker_squares=["f5"],
        color="black", can_retreat=False,
        value=TacticValue(material_delta=300, is_sound=True),
    )
    return TacticalMotifs(capturable_defenders=[cd], hanging=[hanging])


# ---------------------------------------------------------------------------
# Overload chain detection tests
# ---------------------------------------------------------------------------


class TestOverloadHangingDetection:
    def test_disabled_returns_empty(self, monkeypatch):
        """Tier 2 flag off -> no chains detected."""
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_CHAINING", raising=False)
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", raising=False)
        tactics = _make_overload_hanging_tactics()
        chains = _detect_overload_hanging_chains(tactics)
        assert chains == {}

    def test_tier1_only_returns_empty(self, monkeypatch):
        """Tier 1 on but Tier 2 off -> no overload chains."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", raising=False)
        tactics = _make_overload_hanging_tactics()
        chains = _detect_overload_hanging_chains(tactics)
        assert chains == {}

    def test_enabled_detects_link(self, monkeypatch):
        """Both flags on -> overload->hanging chain detected."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        tactics = _make_overload_hanging_tactics()
        chains = _detect_overload_hanging_chains(tactics)
        assert len(chains) == 1
        overloaded_key = ("overloaded", "d4", "n", ("c6", "e6"))
        assert overloaded_key in chains
        # Value should be the hanging key for e6
        hanging_key = ("hanging", "e6", "b", "black")
        assert hanging_key in chains[overloaded_key]

    def test_no_match_when_defended_squares_dont_overlap(self, monkeypatch):
        """Overloaded defends a3,b3 but hanging is on e6 -> no chain."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        overloaded = OverloadedPiece(
            square="d4", piece="n",
            defended_squares=["a3", "b3"],
            color="black",
            value=TacticValue(material_delta=100, is_sound=True, source="heuristic"),
        )
        hanging = HangingPiece(
            square="e6", piece="b", attacker_squares=["f5"],
            color="black",
            value=TacticValue(material_delta=300, is_sound=True),
        )
        tactics = TacticalMotifs(overloaded_pieces=[overloaded], hanging=[hanging])
        chains = _detect_overload_hanging_chains(tactics)
        assert chains == {}


# ---------------------------------------------------------------------------
# Capturable defender chain detection tests
# ---------------------------------------------------------------------------


class TestCapturableDefenderHangingDetection:
    def test_disabled_returns_empty(self, monkeypatch):
        """Tier 2 flag off -> no chains."""
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_CHAINING", raising=False)
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", raising=False)
        tactics = _make_cd_hanging_tactics()
        chains = _detect_capturable_defender_hanging_chains(tactics)
        assert chains == {}

    def test_enabled_detects_link(self, monkeypatch):
        """Both flags on -> cd charge matches hanging square."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        tactics = _make_cd_hanging_tactics()
        chains = _detect_capturable_defender_hanging_chains(tactics)
        assert len(chains) == 1
        cd_key = ("capturable_defender", "d4", "e6")
        hanging_key = ("hanging", "e6", "b", "black")
        assert chains[cd_key] == hanging_key

    def test_no_match_wrong_square(self, monkeypatch):
        """CD charge_square=f6 but hanging on e6 -> no chain."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        cd = CapturableDefender(
            defender_square="d4", defender_piece="n",
            charge_square="f6", charge_piece="r",
            attacker_square="c2", color="black",
            value=TacticValue(material_delta=600, is_sound=True),
        )
        hanging = HangingPiece(
            square="e6", piece="b", attacker_squares=["f5"],
            color="black",
            value=TacticValue(material_delta=300, is_sound=True),
        )
        tactics = TacticalMotifs(capturable_defenders=[cd], hanging=[hanging])
        chains = _detect_capturable_defender_hanging_chains(tactics)
        assert chains == {}
