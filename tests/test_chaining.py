"""Tests for tactical chain detection and rendering.

Covers:
- Chain detection with feature flag on/off
- Merged rendering of pin->hanging chains
- Suppression of standalone hanging when merged into chain
- rendered_keys tracking for both pin and hanging keys
- Preservation of unrelated motifs
- End-to-end: analyze_tactics + render_motifs pipeline
"""

import time

import chess

from server.analysis.tactics import analyze_tactics
from server.analysis.tactics.types import (
    Fork,
    HangingPiece,
    Pin,
    Skewer,
    TacticValue,
    TacticalMotifs,
)
from server.motifs import (
    RenderContext,
    _detect_pin_hanging_chains,
    _render_chain_merged,
    render_motifs,
)


# --- Helpers ---

def _ctx(student_is_white=True) -> RenderContext:
    return RenderContext(
        student_is_white=student_is_white,
        player_color="White" if student_is_white else "Black",
    )


def _make_pin_hanging_tactics(
    defense_notes: str = "defender N on d7 pinned to d8",
) -> TacticalMotifs:
    """Build TacticalMotifs with a pin and a hanging piece linked by defense_notes."""
    pin = Pin(
        pinned_square="d7", pinned_piece="n",
        pinner_square="d1", pinner_piece="R",
        pinned_to="d8", pinned_to_piece="k",
        is_absolute=True, color="white",
        value=TacticValue(material_delta=300, is_sound=True),
    )
    hanging = HangingPiece(
        square="f5", piece="b", attacker_squares=["e4", "e3"],
        color="black", can_retreat=False,
        value=TacticValue(
            material_delta=300, is_sound=True,
            defense_notes=defense_notes,
        ),
    )
    return TacticalMotifs(pins=[pin], hanging=[hanging])


# ---------------------------------------------------------------------------
# Chain detection tests
# ---------------------------------------------------------------------------


class TestChainDetection:
    def test_chain_disabled_returns_empty(self, monkeypatch):
        """Flag off → no chains detected."""
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_CHAINING", raising=False)
        tactics = _make_pin_hanging_tactics()
        chains = _detect_pin_hanging_chains(tactics)
        assert chains == {}

    def test_chain_enabled_detects_link(self, monkeypatch):
        """Flag on → pin->hanging chain detected."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        tactics = _make_pin_hanging_tactics()
        chains = _detect_pin_hanging_chains(tactics)
        assert len(chains) == 1
        pin_key = ("pin", "d1", "d7", "d8", True)
        hanging_key = ("hanging", "f5", "b", "black")
        assert chains[pin_key] == hanging_key

    def test_chain_only_with_defense_notes(self, monkeypatch):
        """Pin + hanging without defense_notes → no merge even with flag on."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        tactics = _make_pin_hanging_tactics(defense_notes="")
        chains = _detect_pin_hanging_chains(tactics)
        assert chains == {}

    def test_chain_no_match_wrong_square(self, monkeypatch):
        """Defense notes mention a square not matching any pin → no chain."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        tactics = _make_pin_hanging_tactics(defense_notes="defender N on c6 pinned to e8")
        chains = _detect_pin_hanging_chains(tactics)
        # c6 doesn't match the pin's pinned_square (d7)
        assert chains == {}


# ---------------------------------------------------------------------------
# Chain rendering tests
# ---------------------------------------------------------------------------


class TestChainRendering:
    def test_chain_disabled_renders_separately(self, monkeypatch):
        """Flag off → pin and hanging render as 2 separate items."""
        monkeypatch.delenv("CHESS_TEACHER_ENABLE_CHAINING", raising=False)
        tactics = _make_pin_hanging_tactics()
        ctx = _ctx(True)
        opps, thrs, obs, rendered_keys = render_motifs(
            tactics, {"pin", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        diff_keys = [r.diff_key for r in all_items]
        assert "pin" in diff_keys
        assert "hanging" in diff_keys
        assert len(all_items) == 2

    def test_chain_enabled_merges(self, monkeypatch):
        """Flag on → 1 merged item, text mentions both pin and "undefended"."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        tactics = _make_pin_hanging_tactics()
        ctx = _ctx(True)
        opps, thrs, obs, rendered_keys = render_motifs(
            tactics, {"pin", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        # Should be 1 merged item (pin), hanging is suppressed
        assert len(all_items) == 1
        text = all_items[0].text.lower()
        assert "pins" in text
        assert "undefended" in text

    def test_chain_suppresses_hanging_duplicate(self, monkeypatch):
        """Hanging piece does NOT appear separately when merged."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        tactics = _make_pin_hanging_tactics()
        ctx = _ctx(True)
        opps, thrs, obs, rendered_keys = render_motifs(
            tactics, {"pin", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        diff_keys = [r.diff_key for r in all_items]
        assert "hanging" not in diff_keys

    def test_chain_hanging_key_in_rendered_keys(self, monkeypatch):
        """Both pin key AND hanging key appear in rendered_keys."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        tactics = _make_pin_hanging_tactics()
        ctx = _ctx(True)
        opps, thrs, obs, rendered_keys = render_motifs(
            tactics, {"pin", "hanging"}, ctx,
        )
        pin_key = ("pin", "d1", "d7", "d8", True)
        hanging_key = ("hanging", "f5", "b", "black")
        assert pin_key in rendered_keys
        assert hanging_key in rendered_keys

    def test_chain_preserves_unrelated_motifs(self, monkeypatch):
        """Forks, skewers etc. unaffected by chain merging."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        tactics = _make_pin_hanging_tactics()
        # Add an unrelated fork
        tactics.forks.append(Fork(
            forking_square="e5", forking_piece="N",
            targets=["c6", "g6"], target_pieces=["r", "q"],
            color="white",
        ))
        ctx = _ctx(True)
        opps, thrs, obs, rendered_keys = render_motifs(
            tactics, {"pin", "hanging", "fork"}, ctx,
        )
        all_items = opps + thrs + obs
        diff_keys = [r.diff_key for r in all_items]
        assert "fork" in diff_keys
        # Pin is merged (present), hanging is suppressed (absent)
        assert "pin" in diff_keys
        assert "hanging" not in diff_keys


# ---------------------------------------------------------------------------
# _render_chain_merged unit test
# ---------------------------------------------------------------------------


class TestRenderChainMerged:
    def test_merged_text_format(self):
        """Merged text includes pin description and 'undefended' clause."""
        pin = Pin(
            pinned_square="d7", pinned_piece="n",
            pinner_square="d1", pinner_piece="R",
            pinned_to="d8", pinned_to_piece="k",
            is_absolute=True, color="white",
        )
        hanging = HangingPiece(
            square="f5", piece="b", attacker_squares=["e4"],
            color="black",
        )
        ctx = _ctx(True)
        text, is_opp = _render_chain_merged(pin, hanging, ctx)
        assert "pins" in text.lower()
        assert "undefended" in text.lower()
        assert "f5" in text
        assert text.endswith(".")
        assert is_opp is True  # white pinner = student's piece = opportunity


# ---------------------------------------------------------------------------
# End-to-end integration tests
# ---------------------------------------------------------------------------


class TestE2EChaining:
    def test_e2e_analyze_and_render_chain(self, monkeypatch):
        """Full pipeline: analyze_tactics on pin+hanging FEN, render with flag on.

        Uses a constructed TacticalMotifs with defense_notes pre-set (since
        _find_hanging doesn't detect pin-blind hanging pieces). Verifies
        that the full render_motifs pipeline merges correctly.
        """
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")

        # Manually construct the motifs as they would appear after valuation
        # with defense_notes populated (simulating a future pin-aware _find_hanging)
        pin = Pin(
            pinned_square="g7", pinned_piece="n",
            pinner_square="g1", pinner_piece="R",
            pinned_to="g8", pinned_to_piece="k",
            is_absolute=True, color="white",
            value=TacticValue(material_delta=300, is_sound=True),
        )
        hanging = HangingPiece(
            square="f5", piece="b", attacker_squares=["e4", "e3"],
            color="black", can_retreat=False,
            value=TacticValue(
                material_delta=300, is_sound=True,
                defense_notes="defender N on g7 pinned to g8",
                related_motifs=["pin:g1-g7-g8"],
            ),
        )
        tactics = TacticalMotifs(pins=[pin], hanging=[hanging])

        ctx = _ctx(True)
        opps, thrs, obs, rendered_keys = render_motifs(
            tactics, {"pin", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        assert len(all_items) == 1
        text = all_items[0].text.lower()
        assert "pins" in text
        assert "undefended" in text
        assert "f5" in text

    def test_e2e_starting_position_no_chains(self, monkeypatch):
        """Starting position → no defense_notes, no chains."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")
        board = chess.Board()
        motifs = analyze_tactics(board)

        # No hanging pieces should have defense_notes in the starting position
        for h in motifs.hanging:
            if h.value:
                assert h.value.defense_notes == "", (
                    f"Unexpected defense_notes on {h.square}: {h.value.defense_notes}"
                )

        chains = _detect_pin_hanging_chains(motifs)
        assert chains == {}

    def test_e2e_multiple_pins_single_chain(self, monkeypatch):
        """Two pins, only one creates hanging → one chain."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")

        pin_linked = Pin(
            pinned_square="d7", pinned_piece="n",
            pinner_square="d1", pinner_piece="R",
            pinned_to="d8", pinned_to_piece="k",
            is_absolute=True, color="white",
            value=TacticValue(material_delta=300, is_sound=True),
        )
        pin_unlinked = Pin(
            pinned_square="f6", pinned_piece="b",
            pinner_square="c3", pinner_piece="B",
            pinned_to="h8", pinned_to_piece="k",
            is_absolute=True, color="white",
            value=TacticValue(material_delta=300, is_sound=True),
        )
        hanging = HangingPiece(
            square="f5", piece="b", attacker_squares=["e4"],
            color="black", can_retreat=False,
            value=TacticValue(
                material_delta=300, is_sound=True,
                defense_notes="defender N on d7 pinned to d8",
            ),
        )
        tactics = TacticalMotifs(
            pins=[pin_linked, pin_unlinked],
            hanging=[hanging],
        )

        chains = _detect_pin_hanging_chains(tactics)
        assert len(chains) == 1
        # Only the linked pin is in the chain
        assert ("pin", "d1", "d7", "d8", True) in chains

        ctx = _ctx(True)
        opps, thrs, obs, rendered_keys = render_motifs(
            tactics, {"pin", "hanging"}, ctx,
        )
        all_items = opps + thrs + obs
        # 2 items: 1 merged pin+hanging, 1 standalone pin
        assert len(all_items) == 2
        diff_keys = [r.diff_key for r in all_items]
        assert diff_keys.count("pin") == 2  # both are "pin" diff_key
        # One should mention "undefended", the other should not
        merged = [r for r in all_items if "undefended" in r.text.lower()]
        standalone = [r for r in all_items if "undefended" not in r.text.lower()]
        assert len(merged) == 1
        assert len(standalone) == 1

    def test_performance_chain_detection(self, monkeypatch):
        """Chain detection on a complex position completes in < 1ms."""
        monkeypatch.setenv("CHESS_TEACHER_ENABLE_CHAINING", "1")

        # Build a moderately complex TacticalMotifs
        pins = [
            Pin(f"p{i}", "n", f"a{i}", "R", f"k{i}", "k",
                True, "white", TacticValue(300, True))
            for i in range(1, 9)
        ]
        hanging = [
            HangingPiece(f"h{i}", "b", [f"x{i}"], "black", False,
                         TacticValue(300, True, defense_notes=f"defender N on p{i} pinned to k{i}"))
            for i in range(1, 5)
        ]
        tactics = TacticalMotifs(pins=pins, hanging=hanging)

        start = time.perf_counter()
        for _ in range(100):
            _detect_pin_hanging_chains(tactics)
        elapsed = (time.perf_counter() - start) / 100

        assert elapsed < 0.001, f"Chain detection took {elapsed*1000:.3f}ms, expected < 1ms"
