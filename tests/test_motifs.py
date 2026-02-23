"""Tests for motifs.py — registry, renderers, tactic keys, motif labels, ray dedup."""

import chess

from server.analysis import (
    BackRankWeakness,
    DiscoveredAttack,
    Fork,
    HangingPiece,
    MatePattern,
    Pin,
    Skewer,
    TacticalMotifs,
    XRayAttack,
)
from server.analysis import _colored
from server.motifs import (
    MOTIF_REGISTRY,
    MotifSpec,
    RenderContext,
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

    def test_all_specs_have_required_fields(self):
        for spec in MOTIF_REGISTRY:
            assert isinstance(spec, MotifSpec)
            assert spec.diff_key
            assert spec.field
            assert spec.key_fn is not None
            assert spec.render_fn is not None

    def test_diff_keys_unique(self):
        keys = [s.diff_key for s in MOTIF_REGISTRY]
        assert len(keys) == len(set(keys))

    def test_fields_match_tactical_motifs(self):
        """Every registry field must be a real attribute of TacticalMotifs."""
        t = TacticalMotifs()
        for spec in MOTIF_REGISTRY:
            assert hasattr(t, spec.field), f"TacticalMotifs has no field '{spec.field}'"


# --- Observation flag tests ---

class TestObservationFlags:
    def test_observation_flags(self):
        """Exactly discovered, back_rank, xray, exposed_king are observations."""
        obs_keys = {s.diff_key for s in MOTIF_REGISTRY if s.is_observation}
        assert obs_keys == {"discovered", "back_rank", "xray", "exposed_king"}

    def test_non_observation_flags(self):
        """All other motifs are not observations."""
        non_obs = {s.diff_key for s in MOTIF_REGISTRY if not s.is_observation}
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
        assert "fork by White N on e5" in desc
        assert "Black R on c6" in desc
        assert is_opp is True

    def test_render_fork_opponent(self):
        fork = Fork("e4", "n", ["d2", "f2"], ["R", "Q"])
        desc, is_opp = render_fork(fork, _ctx(True))
        assert is_opp is False

    def test_render_fork_wins_piece(self):
        fork = Fork("f7", "N", ["e8", "h8"], ["k", "r"])
        desc, is_opp = render_fork(fork, _ctx(True))
        assert "wins the" in desc

    def test_render_pin(self):
        pin = Pin(
            pinned_piece="N", pinned_square="c6",
            pinner_piece="B", pinner_square="b5",
            pinned_to="e8", pinned_to_piece="k",
            is_absolute=True,
        )
        desc, is_opp = render_pin(pin, _ctx(True))
        assert "pin:" in desc
        assert "cannot move" in desc
        assert is_opp is True

    def test_render_skewer(self):
        skewer = Skewer(
            attacker_piece="R", attacker_square="e1",
            front_piece="q", front_square="e5",
            behind_piece="k", behind_square="e8",
        )
        desc, is_opp = render_skewer(skewer, _ctx(True))
        assert "skewer by White R" in desc
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


# --- render_motifs 3-bucket tests ---

class TestRenderMotifsThreeBuckets:
    def test_fork_goes_to_opportunities(self):
        """Fork by student's piece should go to opportunities, not observations."""
        tactics = TacticalMotifs(forks=[Fork("e5", "N", ["c6", "g6"], ["r", "q"])])
        ctx = _ctx(True)
        opps, thrs, obs = render_motifs(tactics, {"fork"}, ctx)
        assert len(opps) == 1
        assert len(thrs) == 0
        assert len(obs) == 0
        assert "fork" in opps[0].lower()

    def test_back_rank_goes_to_observations(self):
        """Back rank weakness should go to observations regardless of is_opp."""
        tactics = TacticalMotifs(
            back_rank_weaknesses=[BackRankWeakness(weak_color="Black", king_square="g8")]
        )
        ctx = _ctx(True)
        opps, thrs, obs = render_motifs(tactics, {"back_rank"}, ctx)
        assert len(obs) == 1
        assert len(opps) == 0
        assert len(thrs) == 0
        assert "back rank" in obs[0].lower()

    def test_mixed_motifs_three_buckets(self):
        """Fork + back rank → fork in opps, back rank in obs."""
        tactics = TacticalMotifs(
            forks=[Fork("e5", "N", ["c6", "g6"], ["r", "q"])],
            back_rank_weaknesses=[BackRankWeakness(weak_color="Black", king_square="g8")],
        )
        ctx = _ctx(True)
        opps, thrs, obs = render_motifs(tactics, {"fork", "back_rank"}, ctx)
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
        assert ("pin", "b5", "c6") in keys

    def test_single_fork(self):
        fork = Fork("e5", "N", ["c6", "g6"])
        keys = all_tactic_keys(TacticalMotifs(forks=[fork]))
        assert len(keys) == 1
        assert ("fork", "e5", ("c6", "g6")) in keys

    def test_multiple_types(self):
        pin = Pin("c6", "N", "b5", "B", "e8", "k", True)
        fork = Fork("e5", "N", ["c6", "g6"])
        keys = all_tactic_keys(TacticalMotifs(pins=[pin], forks=[fork]))
        assert len(keys) == 2

    def test_mate_pattern(self):
        mp = MatePattern("smothered")
        keys = all_tactic_keys(TacticalMotifs(mate_patterns=[mp]))
        assert ("mate_pattern", "smothered") in keys


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
