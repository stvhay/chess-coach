"""Tests for motifs.py — registry, renderers, tactic keys, motif labels, ray dedup."""

import chess

from server.analysis import (
    BackRankWeakness,
    CapturableDefender,
    DiscoveredAttack,
    ExposedKing,
    Fork,
    HangingPiece,
    MatePattern,
    OverloadedPiece,
    Pin,
    Skewer,
    TacticalMotifs,
    XRayAttack,
)
from server.analysis import _colored
from server.motifs import (
    HIGH_VALUE_KEYS,
    MODERATE_VALUE_KEYS,
    MOTIF_REGISTRY,
    MotifSpec,
    RenderedMotif,
    RenderContext,
    RenderMode,
    all_tactic_keys,
    motif_labels,
    render_fork,
    render_hanging,
    render_pin,
    render_skewer,
    render_motifs,
    _piece_is_students,
    _dedup_ray_motifs,
)


# --- Helper ---

def _ctx(student_is_white=True) -> RenderContext:
    return RenderContext(
        student_is_white=student_is_white,
        player_color="White" if student_is_white else "Black",
    )


# --- Registry structure tests ---

class TestRegistry:
    def test_registry_has_14_entries(self):
        assert len(MOTIF_REGISTRY) == 14

    def test_registry_is_dict(self):
        assert isinstance(MOTIF_REGISTRY, dict)

    def test_all_specs_have_required_fields(self):
        for spec in MOTIF_REGISTRY.values():
            assert isinstance(spec, MotifSpec)
            assert spec.diff_key
            assert spec.field
            assert spec.key_fn is not None
            assert spec.render_fn is not None

    def test_diff_keys_match_dict_keys(self):
        """Each dict key matches the spec's diff_key."""
        for key, spec in MOTIF_REGISTRY.items():
            assert key == spec.diff_key

    def test_fields_match_tactical_motifs(self):
        """Every registry field must be a real attribute of TacticalMotifs."""
        t = TacticalMotifs()
        for spec in MOTIF_REGISTRY.values():
            assert hasattr(t, spec.field), f"TacticalMotifs has no field '{spec.field}'"

    def test_priority_field(self):
        """Every spec has an int priority between 1 and 100."""
        for spec in MOTIF_REGISTRY.values():
            assert isinstance(spec.priority, int)
            assert 1 <= spec.priority <= 100, f"{spec.diff_key} priority {spec.priority} out of range"

    def test_render_mode_enum(self):
        """RenderMode has exactly 3 members."""
        assert len(RenderMode) == 3
        assert RenderMode.OPPORTUNITY.value == "opportunity"
        assert RenderMode.THREAT.value == "threat"
        assert RenderMode.POSITION.value == "position"

    def test_scoring_sets_are_registry_subsets(self):
        """HIGH_VALUE_KEYS and MODERATE_VALUE_KEYS must be subsets of registry keys."""
        assert HIGH_VALUE_KEYS <= MOTIF_REGISTRY.keys()
        assert MODERATE_VALUE_KEYS <= MOTIF_REGISTRY.keys()
        assert HIGH_VALUE_KEYS & MODERATE_VALUE_KEYS == set()  # no overlap


# --- Observation flag tests ---

class TestObservationFlags:
    def test_observation_flags(self):
        """Exactly discovered, back_rank, xray, exposed_king are observations."""
        obs_keys = {s.diff_key for s in MOTIF_REGISTRY.values() if s.is_observation}
        assert obs_keys == {"discovered", "back_rank", "xray", "exposed_king"}

    def test_non_observation_flags(self):
        """All other motifs are not observations."""
        non_obs = {s.diff_key for s in MOTIF_REGISTRY.values() if not s.is_observation}
        assert "pin" in non_obs
        assert "fork" in non_obs
        assert "skewer" in non_obs
        assert "hanging" in non_obs
        assert "mate_threat" in non_obs


# --- Shared helper tests ---

class TestHelpers:
    def test_colored_white(self):
        assert _colored("N") == "White N"

    def test_colored_black(self):
        assert _colored("n") == "Black N"

    def test_piece_is_students_white(self):
        assert _piece_is_students("N", True) is True
        assert _piece_is_students("n", True) is False

    def test_piece_is_students_black(self):
        assert _piece_is_students("n", False) is True
        assert _piece_is_students("N", False) is False


# --- Renderer tests ---

class TestMotifRenderers:
    def test_render_fork(self):
        fork = Fork("e5", "N", ["c6", "g6"], ["r", "q"])
        desc, is_opp = render_fork(fork, _ctx(True))
        assert "your knight on e5 forks" in desc.lower()
        assert "their rook on c6" in desc.lower()
        assert is_opp is True

    def test_render_fork_opponent(self):
        fork = Fork("e4", "n", ["d2", "f2"], ["R", "Q"])
        desc, is_opp = render_fork(fork, _ctx(True))
        assert is_opp is False

    def test_render_fork_wins_piece(self):
        fork = Fork("f7", "N", ["e8", "h8"], ["k", "r"])
        desc, is_opp = render_fork(fork, _ctx(True))
        assert "wins" in desc.lower()

    def test_render_pin_fork(self):
        """Pin-fork uses 'pins and also attacks' language instead of 'forks'."""
        fork = Fork("g5", "B", ["f6", "h6"], ["n", "p"], is_pin_fork=True)
        desc, is_opp = render_fork(fork, _ctx(True))
        assert "pins and also attacks" in desc.lower()
        assert "forks" not in desc.lower()

    def test_render_regular_fork_no_pin_fork_language(self):
        """Regular fork should use 'forks' language, not pin-fork language."""
        fork = Fork("e5", "N", ["c6", "g6"], ["r", "q"], is_pin_fork=False)
        desc, is_opp = render_fork(fork, _ctx(True))
        assert "forks" in desc.lower()
        assert "pins and also attacks" not in desc.lower()

    def test_render_pin(self):
        # White bishop pins Black knight to Black king
        pin = Pin(
            pinned_piece="n", pinned_square="c6",
            pinner_piece="B", pinner_square="b5",
            pinned_to="e8", pinned_to_piece="k",
            is_absolute=True,
        )
        desc, is_opp = render_pin(pin, _ctx(True))
        assert "your bishop on b5 pins" in desc.lower()
        assert "their knight on c6" in desc.lower()
        assert "cannot move" in desc
        assert is_opp is True

    def test_render_skewer(self):
        skewer = Skewer(
            attacker_piece="R", attacker_square="e1",
            front_piece="q", front_square="e5",
            behind_piece="k", behind_square="e8",
        )
        desc, is_opp = render_skewer(skewer, _ctx(True))
        assert "your rook on e1 skewers" in desc.lower()
        assert is_opp is True

    def test_render_hanging_opponent(self):
        hp = HangingPiece(square="d5", piece="n", attacker_squares=["e3"], color="Black")
        desc, is_opp = render_hanging(hp, _ctx(True))
        assert "hanging" in desc.lower() or "undefended" in desc.lower()
        assert is_opp is True

    def test_render_hanging_student(self):
        hp = HangingPiece(square="d5", piece="N", attacker_squares=["e3"], color="White")
        desc, is_opp = render_hanging(hp, _ctx(True))
        assert is_opp is False

    def test_rendered_motif_fields(self):
        """RenderedMotif has expected fields."""
        rm = RenderedMotif(text="test", is_opportunity=True, diff_key="fork", priority=20)
        assert rm.text == "test"
        assert rm.is_opportunity is True
        assert rm.diff_key == "fork"
        assert rm.priority == 20


# --- render_motifs 3-bucket tests ---

class TestRenderMotifsThreeBuckets:
    def test_fork_goes_to_opportunities(self):
        """Fork by student's piece should go to opportunities, not observations."""
        tactics = TacticalMotifs(forks=[Fork("e5", "N", ["c6", "g6"], ["r", "q"])])
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(tactics, {"fork"}, ctx)
        assert len(opps) == 1
        assert len(thrs) == 0
        assert len(obs) == 0
        assert isinstance(opps[0], RenderedMotif)
        assert "fork" in opps[0].text.lower()
        assert opps[0].diff_key == "fork"
        assert opps[0].priority == 20

    def test_back_rank_goes_to_observations(self):
        """Back rank weakness should go to observations regardless of is_opp."""
        tactics = TacticalMotifs(
            back_rank_weaknesses=[BackRankWeakness(weak_color="Black", king_square="g8")]
        )
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(tactics, {"back_rank"}, ctx)
        assert len(obs) == 1
        assert len(opps) == 0
        assert len(thrs) == 0
        assert "back rank" in obs[0].text.lower()

    def test_mixed_motifs_three_buckets(self):
        """Fork + back rank → fork in opps, back rank in obs."""
        tactics = TacticalMotifs(
            forks=[Fork("e5", "N", ["c6", "g6"], ["r", "q"])],
            back_rank_weaknesses=[BackRankWeakness(weak_color="Black", king_square="g8")],
        )
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(tactics, {"fork", "back_rank"}, ctx)
        assert len(opps) == 1
        assert len(obs) == 1


# --- all_tactic_keys tests ---

class TestAllTacticKeys:
    def test_empty_tactics_empty_keys(self):
        assert all_tactic_keys(TacticalMotifs()) == set()

    def test_single_pin(self):
        pin = Pin("c6", "N", "b5", "B", "e8", "k", True)
        keys = all_tactic_keys(TacticalMotifs(pins=[pin]))
        assert len(keys) == 1
        assert ("pin", "b5", "c6", "e8", True) in keys

    def test_single_fork(self):
        fork = Fork("e5", "N", ["c6", "g6"])
        keys = all_tactic_keys(TacticalMotifs(forks=[fork]))
        assert len(keys) == 1
        assert ("fork", "e5", (("c6",), ("g6",))) in keys

    def test_multiple_types(self):
        pin = Pin("c6", "N", "b5", "B", "e8", "k", True)
        fork = Fork("e5", "N", ["c6", "g6"])
        keys = all_tactic_keys(TacticalMotifs(pins=[pin], forks=[fork]))
        assert len(keys) == 2

    def test_mate_pattern(self):
        mp = MatePattern("smothered")
        keys = all_tactic_keys(TacticalMotifs(mate_patterns=[mp]))
        assert ("mate_pattern", "smothered") in keys

    def test_pin_key_includes_pinned_to_and_absolute(self):
        """Pin key must include pinned_to and is_absolute to distinguish mutations."""
        pin_abs = Pin("c6", "n", "b5", "B", "e8", "k", True)
        pin_rel = Pin("c6", "n", "b5", "B", "d7", "q", False)
        keys_abs = all_tactic_keys(TacticalMotifs(pins=[pin_abs]))
        keys_rel = all_tactic_keys(TacticalMotifs(pins=[pin_rel]))
        assert keys_abs != keys_rel
        key_abs = next(iter(keys_abs))
        assert "e8" in key_abs
        assert True in key_abs

    def test_hanging_key_includes_color(self):
        """Hanging key must include color to distinguish sides."""
        hp_w = HangingPiece("d5", "N", ["e3"], color="White")
        hp_b = HangingPiece("d5", "n", ["e3"], color="Black")
        keys_w = all_tactic_keys(TacticalMotifs(hanging=[hp_w]))
        keys_b = all_tactic_keys(TacticalMotifs(hanging=[hp_b]))
        assert keys_w != keys_b

    def test_fork_key_includes_target_pieces(self):
        """Fork key must include target pieces to distinguish piece types on same squares."""
        fork_rq = Fork("e5", "N", ["c6", "g6"], ["r", "q"])
        fork_bn = Fork("e5", "N", ["c6", "g6"], ["b", "n"])
        keys_rq = all_tactic_keys(TacticalMotifs(forks=[fork_rq]))
        keys_bn = all_tactic_keys(TacticalMotifs(forks=[fork_bn]))
        assert keys_rq != keys_bn

    def test_capturable_defender_key_includes_charge(self):
        """Capturable defender key must include charge_square."""
        cd1 = CapturableDefender("d5", "N", "e4", "B", "c3", color="Black")
        cd2 = CapturableDefender("d5", "N", "f6", "R", "c3", color="Black")
        keys1 = all_tactic_keys(TacticalMotifs(capturable_defenders=[cd1]))
        keys2 = all_tactic_keys(TacticalMotifs(capturable_defenders=[cd2]))
        assert keys1 != keys2

    def test_overloaded_key_includes_defended_squares(self):
        """Overloaded key must include defended_squares."""
        op1 = OverloadedPiece("d5", "N", ["c3", "e3"], color="Black")
        op2 = OverloadedPiece("d5", "N", ["c3", "f4"], color="Black")
        keys1 = all_tactic_keys(TacticalMotifs(overloaded_pieces=[op1]))
        keys2 = all_tactic_keys(TacticalMotifs(overloaded_pieces=[op2]))
        assert keys1 != keys2

    def test_discovered_key_includes_blocker(self):
        """Discovered attack key must include blocker_square."""
        da1 = DiscoveredAttack("f3", "N", "d1", "Q", "g4", "b")
        da2 = DiscoveredAttack("e4", "B", "d1", "Q", "g4", "b")
        keys1 = all_tactic_keys(TacticalMotifs(discovered_attacks=[da1]))
        keys2 = all_tactic_keys(TacticalMotifs(discovered_attacks=[da2]))
        assert keys1 != keys2


# --- motif_labels tests ---

class TestMotifLabels:
    def test_empty(self):
        assert motif_labels(TacticalMotifs()) == set()

    def test_with_fork(self):
        tactics = TacticalMotifs(forks=[Fork("e5", "N", ["d7", "f7"])])
        assert "fork" in motif_labels(tactics)

    def test_checkmate(self):
        board = chess.Board("rnb1kbnr/pppp1ppp/4p3/8/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
        assert board.is_checkmate()
        assert "checkmate" in motif_labels(TacticalMotifs(), board)

    def test_mate_pattern_uses_pattern_name(self):
        tactics = TacticalMotifs(mate_patterns=[MatePattern("back_rank")])
        labels = motif_labels(tactics)
        assert "mate_back_rank" in labels

    def test_multiple_fields(self):
        tactics = TacticalMotifs(
            pins=[Pin("c6", "N", "b5", "B", "e8", "k", True)],
            forks=[Fork("e5", "N", ["d7", "f7"])],
        )
        labels = motif_labels(tactics)
        assert "pin" in labels
        assert "fork" in labels


# --- Ray dedup tests ---

class TestRayDedup:
    def test_pin_beats_xray_same_direction(self):
        """Pin and x-ray on same ray -> keep pin only."""
        pin = Pin("c6", "n", "a4", "B", "e8", "k", True)
        xa = XRayAttack("a4", "B", "c6", "n", "e8", "k")
        tactics = TacticalMotifs(pins=[pin], xray_attacks=[xa])
        result = _dedup_ray_motifs(tactics)
        assert len(result["pins"]) == 1
        assert len(result["xray_attacks"]) == 0

    def test_independent_rays_both_kept(self):
        """Pin and x-ray on different rays -> both kept."""
        pin = Pin("c6", "n", "a4", "B", "e8", "k", True)
        xa = XRayAttack("h1", "R", "h4", "p", "h8", "r")
        tactics = TacticalMotifs(pins=[pin], xray_attacks=[xa])
        result = _dedup_ray_motifs(tactics)
        assert len(result["pins"]) == 1
        assert len(result["xray_attacks"]) == 1

    def test_discovered_deduped_against_xray(self):
        """X-ray and discovered attack on same ray -> keep x-ray only."""
        # B on g4 x-rays through Nf3 to Qd1
        xa = XRayAttack(
            slider_square="g4", slider_piece="b",
            through_square="f3", through_piece="N",
            target_square="d1", target_piece="Q",
        )
        # Q on d1 discovers through Nf3 to Bg4
        da = DiscoveredAttack(
            blocker_square="f3", blocker_piece="N",
            slider_square="d1", slider_piece="Q",
            target_square="g4", target_piece="b",
        )
        tactics = TacticalMotifs(xray_attacks=[xa], discovered_attacks=[da])
        result = _dedup_ray_motifs(tactics)
        assert len(result["xray_attacks"]) == 1
        assert len(result["discovered_attacks"]) == 0

    def test_discovered_kept_when_no_xray(self):
        """Discovered attack with no competing motif survives dedup."""
        da = DiscoveredAttack(
            blocker_square="f3", blocker_piece="N",
            slider_square="d1", slider_piece="Q",
            target_square="g4", target_piece="b",
        )
        tactics = TacticalMotifs(discovered_attacks=[da])
        result = _dedup_ray_motifs(tactics)
        assert len(result["discovered_attacks"]) == 1

    def test_empty_tactics_empty_result(self):
        result = _dedup_ray_motifs(TacticalMotifs())
        assert result == {"pins": [], "skewers": [], "xray_attacks": [], "discovered_attacks": []}


# --- render_motifs improvements tests ---

class TestRenderMotifsImprovements:
    def test_sorted_by_priority(self):
        """Fork (20) should come before exposed_king (50) in opportunities."""
        tactics = TacticalMotifs(
            forks=[Fork("e5", "N", ["c6", "g6"], ["r", "q"])],
            exposed_kings=[ExposedKing(color="black", king_square="e8")],
        )
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(tactics, {"fork", "exposed_king"}, ctx)
        # Fork goes to opps (priority 20), exposed_king goes to obs (priority 50)
        assert len(opps) >= 1
        assert opps[0].diff_key == "fork"
        # exposed_king is an observation, so it goes to obs
        assert any(o.diff_key == "exposed_king" for o in obs)

    def test_max_items(self):
        """max_items=1 should cap each bucket to 1 result."""
        tactics = TacticalMotifs(
            forks=[
                Fork("e5", "N", ["c6", "g6"], ["r", "q"]),
                Fork("d4", "N", ["c6", "e6"], ["r", "b"]),
            ],
        )
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(tactics, {"fork"}, ctx, max_items=1)
        assert len(opps) == 1

    def test_fork_suppresses_hanging_same_square(self):
        """Fork on d5 targeting c6+g6 + hanging on c6 → hanging on c6 removed."""
        tactics = TacticalMotifs(
            forks=[Fork("d5", "N", ["c6", "g6"], ["r", "q"])],
            hanging=[HangingPiece(square="c6", piece="r", attacker_squares=["d5"], color="Black")],
        )
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(tactics, {"fork", "hanging"}, ctx)
        all_keys = [r.diff_key for r in opps + thrs + obs]
        assert "fork" in all_keys
        assert "hanging" not in all_keys

    def test_fork_no_suppression_different_square(self):
        """Fork on d5 targeting c6+g6 + hanging on e4 → both kept."""
        tactics = TacticalMotifs(
            forks=[Fork("d5", "N", ["c6", "g6"], ["r", "q"])],
            hanging=[HangingPiece(square="e4", piece="n", attacker_squares=["f2"], color="Black")],
        )
        ctx = _ctx(True)
        opps, thrs, obs, _ = render_motifs(tactics, {"fork", "hanging"}, ctx)
        all_keys = [r.diff_key for r in opps + thrs + obs]
        assert "fork" in all_keys
        assert "hanging" in all_keys


# --- rendered_keys tests ---

class TestRenderedKeys:
    def test_render_motifs_returns_four_tuple(self):
        """render_motifs returns (opps, thrs, obs, rendered_keys)."""
        tactics = TacticalMotifs(forks=[Fork("e5", "N", ["c6", "g6"], ["r", "q"])])
        ctx = _ctx(True)
        result = render_motifs(tactics, {"fork"}, ctx)
        assert len(result) == 4
        opps, thrs, obs, rendered_keys = result
        assert isinstance(rendered_keys, set)
        assert len(rendered_keys) == 1  # one fork rendered

    def test_rendered_keys_excludes_filtered_motifs(self):
        """Motifs filtered by new_keys should not appear in rendered_keys."""
        fork_a = Fork("d5", "N", ["c3", "f6"], ["B", "R"])
        fork_b = Fork("e4", "N", ["c5", "g5"], ["B", "Q"])
        tactics = TacticalMotifs(forks=[fork_a, fork_b])
        ctx = _ctx(True)
        # Only include fork_b's key in new_keys
        fork_spec = MOTIF_REGISTRY["fork"]
        key_b = fork_spec.key_fn(fork_b)
        opps, thrs, obs, rendered_keys = render_motifs(
            tactics, {"fork"}, ctx, new_keys={key_b}
        )
        assert key_b in rendered_keys
        key_a = fork_spec.key_fn(fork_a)
        assert key_a not in rendered_keys

    def test_rendered_keys_excludes_empty_renders(self):
        """Motifs that render to empty text should not appear in rendered_keys."""
        xa = XRayAttack("a4", "B", "c6", "N", "e8", "K")
        tactics = TacticalMotifs(xray_attacks=[xa])
        ctx = _ctx(True)
        opps, thrs, obs, rendered_keys = render_motifs(tactics, {"xray"}, ctx)
        assert len(rendered_keys) == 0
