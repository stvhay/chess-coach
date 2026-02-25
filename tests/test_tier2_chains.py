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


# ---------------------------------------------------------------------------
# Overload chain rendering tests
# ---------------------------------------------------------------------------


class TestOverloadChainRendering:
    def test_disabled_renders_separately(self, monkeypatch):
        """Tier 2 off -> overloaded and hanging render as 2 items."""
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_CHAINING", raising=False)
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", raising=False)
        tactics = _make_overload_hanging_tactics()
        ctx = _ctx(True)
        opps, thrs, obs, rendered_keys = render_motifs(
            tactics, {"overloaded", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        diff_keys = [r.diff_key for r in all_items]
        assert "overloaded" in diff_keys
        assert "hanging" in diff_keys
        assert len(all_items) == 2

    def test_enabled_merges(self, monkeypatch):
        """Tier 2 on -> 1 merged item, hanging is suppressed."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        tactics = _make_overload_hanging_tactics()
        ctx = _ctx(True)
        opps, thrs, obs, rendered_keys = render_motifs(
            tactics, {"overloaded", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        # Hanging on e6 is suppressed — only overloaded rendered (with merged text)
        assert len(all_items) == 1
        text = all_items[0].text.lower()
        assert "overloaded" in text
        assert "e6" in text
        assert "hanging" in text

    def test_suppresses_hanging_duplicate(self, monkeypatch):
        """Hanging diff_key does NOT appear in rendered items."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        tactics = _make_overload_hanging_tactics()
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(
            tactics, {"overloaded", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        diff_keys = [r.diff_key for r in all_items]
        assert "hanging" not in diff_keys

    def test_hanging_key_in_rendered_keys(self, monkeypatch):
        """Both overloaded key AND hanging key appear in rendered_keys."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        tactics = _make_overload_hanging_tactics()
        ctx = _ctx(True)
        _, _, _, rendered_keys = render_motifs(
            tactics, {"overloaded", "hanging"}, ctx,
        )
        hanging_key = ("hanging", "e6", "b", "black")
        overloaded_key = ("overloaded", "d4", "n", ("c6", "e6"))
        assert hanging_key in rendered_keys
        assert overloaded_key in rendered_keys

    def test_preserves_unrelated_motifs(self, monkeypatch):
        """Other motifs unaffected by Tier 2 merging."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        tactics = _make_overload_hanging_tactics()
        # Add an unrelated hanging piece on a different square
        tactics.hanging.append(HangingPiece(
            square="a1", piece="R", attacker_squares=["a8"],
            color="white", can_retreat=True,
            value=TacticValue(material_delta=500, is_sound=True),
        ))
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(
            tactics, {"overloaded", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        # e6 hanging suppressed, a1 hanging preserved, overloaded merged
        assert len(all_items) == 2
        texts = [r.text.lower() for r in all_items]
        assert any("a1" in t for t in texts)  # unrelated hanging preserved


# ---------------------------------------------------------------------------
# Capturable defender chain rendering tests
# ---------------------------------------------------------------------------


class TestCapturableDefenderChainRendering:
    def test_disabled_renders_separately(self, monkeypatch):
        """Tier 2 off -> cd and hanging render as 2 items."""
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_CHAINING", raising=False)
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", raising=False)
        tactics = _make_cd_hanging_tactics()
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(
            tactics, {"capturable_defender", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        diff_keys = [r.diff_key for r in all_items]
        assert "capturable_defender" in diff_keys
        assert "hanging" in diff_keys
        assert len(all_items) == 2

    def test_enabled_suppresses_hanging(self, monkeypatch):
        """Tier 2 on -> hanging suppressed, cd renders normally (already says 'left hanging')."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        tactics = _make_cd_hanging_tactics()
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(
            tactics, {"capturable_defender", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        assert len(all_items) == 1
        assert all_items[0].diff_key == "capturable_defender"

    def test_hanging_key_tracked(self, monkeypatch):
        """Suppressed hanging key still in rendered_keys."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")
        tactics = _make_cd_hanging_tactics()
        ctx = _ctx(True)
        _, _, _, rendered_keys = render_motifs(
            tactics, {"capturable_defender", "hanging"}, ctx,
        )
        hanging_key = ("hanging", "e6", "b", "black")
        assert hanging_key in rendered_keys


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


class TestTier2Performance:
    def test_chain_detection_under_1ms(self, monkeypatch):
        """Both Tier 2 detection functions complete in < 1ms."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "1")

        overloaded = [
            OverloadedPiece(f"d{i}", "n", [f"c{i}", f"e{i}"], "black",
                            TacticValue(100, True, source="heuristic"))
            for i in range(1, 9)
        ]
        hanging = [
            HangingPiece(f"e{i}", "b", [f"f{i}"], "black", False,
                         TacticValue(300, True))
            for i in range(1, 5)
        ]
        cds = [
            CapturableDefender(f"d{i}", "n", f"e{i}", "b", f"c{i}", "black",
                               TacticValue(600, True))
            for i in range(1, 5)
        ]
        tactics = TacticalMotifs(
            overloaded_pieces=overloaded,
            hanging=hanging,
            capturable_defenders=cds,
        )

        start = time.perf_counter()
        for _ in range(100):
            _detect_overload_hanging_chains(tactics)
            _detect_capturable_defender_hanging_chains(tactics)
        elapsed = (time.perf_counter() - start) / 100

        assert elapsed < 0.001, f"Tier 2 detection took {elapsed*1000:.3f}ms, expected < 1ms"
