"""Coaching prompt evaluation tests.

Three layers:
1. Structural tests (always run) — verify prompt format, length, perspective
   consistency, and tactical content from known positions with mocked engine.
2. Integration tests (run with `pytest -m integration`) — use real Stockfish
   engine to verify the full build_coaching_tree/serialize_report pipeline across
   diverse scenarios.
3. Live LLM tests (run with `pytest -m live`) — send prompts to the real
   Ollama instance and print prompt/response pairs for human evaluation.

Run structural tests:  uv run pytest tests/test_coaching_prompts.py
Run integration tests: uv run pytest tests/test_coaching_prompts.py -m integration -s
Run live tests:        uv run pytest tests/test_coaching_prompts.py -m live -s
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import chess
import pytest

from server.analysis import TacticalMotifs
from server.coach import _classify_move, _cp_value, MoveQuality
from server.elo_profiles import get_profile
from server.engine import EngineAnalysis, Evaluation, LineInfo
from server.game_tree import GameTree, build_coaching_tree
from server.llm import ChessTeacher
from server.report import serialize_report


def _live_teacher() -> ChessTeacher:
    """Create a ChessTeacher for live/integration tests using env vars."""
    return ChessTeacher(
        base_url=os.environ.get("LLM_BASE_URL", "https://ollama.st5ve.com"),
        model=os.environ.get("LLM_MODEL", "qwen2.5:14b"),
        api_key=os.environ.get("LLM_API_KEY"),
    )


# ---------------------------------------------------------------------------
# Test positions — each is a (FEN before move, player UCI, description) tuple
# plus mock engine data that simulates what Stockfish would return.
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, dict] = {
    "pin_and_hanging": {
        "description": "Student plays Nc3, gets pinned by Bb4, pawn on d4 hangs",
        # After 1.e4 e5 2.d4 exd4 3.Nf3 Bb4+
        "fen": "rnbqk1nr/pppp1ppp/8/8/1b1pP3/5N2/PPP2PPP/RNBQKB1R w KQkq - 2 4",
        "player_move": "b1c3",  # Nc3 — bad, gets pinned
        "screen_lines": [
            LineInfo(uci="c2c3", san="c3", score_cp=40, score_mate=None,
                     pv=["c2c3", "d4c3", "b2c3", "b4c3"], depth=10),
            LineInfo(uci="b1d2", san="Nbd2", score_cp=30, score_mate=None,
                     pv=["b1d2", "d7d5", "e4d5"], depth=10),
            LineInfo(uci="b1c3", san="Nc3", score_cp=-50, score_mate=None,
                     pv=["b1c3", "d4c3", "b2c3", "b4c3"], depth=10),
        ],
        "validate_evals": [
            # deep eval for c3
            Evaluation(score_cp=45, score_mate=None, depth=16,
                       best_move="d4c3", pv=["d4c3", "b2c3", "b4c3"]),
            # deep eval for Nbd2
            Evaluation(score_cp=35, score_mate=None, depth=16,
                       best_move="d7d5", pv=["d7d5", "e4d5"]),
            # deep eval for Nc3
            Evaluation(score_cp=-60, score_mate=None, depth=16,
                       best_move="d4c3", pv=["d4c3", "b2c3"]),
        ],
        # player move deep eval
        "player_eval": Evaluation(
            score_cp=-60, score_mate=None, depth=16,
            best_move="d4c3", pv=["d4c3", "b2c3", "b4c3"],
        ),
        "quality": "mistake",
        "cp_loss": 100,
        "expect_in_prompt": ["# Student Move", "4. Nc3", "# Stronger Alternative"],
        "expect_not_in_prompt": ["You played"],
    },
    "missed_fork": {
        "description": "Student plays quiet Bd3 instead of Nxf7 forking K+R",
        # White knight on g5 can take f7 (Nxf7) — classic fork
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p1N1/2B1P3/8/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "player_move": "c4d3",  # Bd3 — passive
        "screen_lines": [
            LineInfo(uci="g5f7", san="Nxf7", score_cp=300, score_mate=None,
                     pv=["g5f7", "e8f7", "c4f7"], depth=10),
            LineInfo(uci="d2d3", san="d3", score_cp=50, score_mate=None,
                     pv=["d2d3", "d7d6"], depth=10),
        ],
        "validate_evals": [
            Evaluation(score_cp=310, score_mate=None, depth=16,
                       best_move="e8f7", pv=["e8f7", "c4f7"]),
            Evaluation(score_cp=55, score_mate=None, depth=16,
                       best_move="d7d6", pv=["d7d6"]),
        ],
        "player_eval": Evaluation(
            score_cp=40, score_mate=None, depth=16,
            best_move="d7d6", pv=["d7d6"],
        ),
        "quality": "blunder",
        "cp_loss": 260,
        "expect_in_prompt": ["# Student Move", "4. Bd3", "Nxf7"],
        "expect_not_in_prompt": ["You played"],
    },
    "good_move": {
        "description": "Student plays the engine's top choice — should be brief",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "player_move": "e2e4",
        "screen_lines": [
            LineInfo(uci="e2e4", san="e4", score_cp=30, score_mate=None,
                     pv=["e2e4", "e7e5"], depth=10),
            LineInfo(uci="d2d4", san="d4", score_cp=25, score_mate=None,
                     pv=["d2d4", "d7d5"], depth=10),
        ],
        "validate_evals": [
            Evaluation(score_cp=30, score_mate=None, depth=16,
                       best_move="e7e5", pv=["e7e5", "g1f3"]),
            Evaluation(score_cp=25, score_mate=None, depth=16,
                       best_move="d7d5", pv=["d7d5", "c2c4"]),
        ],
        "player_eval": Evaluation(
            score_cp=30, score_mate=None, depth=16,
            best_move="e7e5", pv=["e7e5", "g1f3"],
        ),
        "quality": "good",
        "cp_loss": 0,
        "expect_in_prompt": ["# Student Move", "1. e4", "good"],
        "expect_not_in_prompt": ["You played"],
    },
}


def _mock_engine(scenario: dict) -> AsyncMock:
    """Build a mock engine that returns canned data for a scenario."""
    engine = AsyncMock()
    engine.analyze_lines = AsyncMock(return_value=scenario["screen_lines"])

    # validate pass: one eval per screen line candidate, then player eval
    all_evals = list(scenario["validate_evals"]) + [scenario["player_eval"]]
    engine.evaluate = AsyncMock(side_effect=all_evals)
    return engine


async def _build_prompt_for_scenario(name: str) -> tuple[str, GameTree]:
    """Run the full game tree pipeline for a scenario, return (prompt, tree)."""
    s = SCENARIOS[name]
    board = chess.Board(s["fen"])
    profile = get_profile("intermediate")
    engine = _mock_engine(s)

    eval_before = Evaluation(
        score_cp=s["screen_lines"][0].score_cp,
        score_mate=None, depth=12,
        best_move=s["screen_lines"][0].uci,
        pv=[s["screen_lines"][0].uci],
    )

    tree = await build_coaching_tree(engine, board, s["player_move"], eval_before, profile)

    prompt = serialize_report(
        tree,
        quality=s["quality"],
        cp_loss=s["cp_loss"],
    )
    return prompt, tree


# ---------------------------------------------------------------------------
# Structural tests — always run, verify prompt shape
# ---------------------------------------------------------------------------

class TestPromptStructure:
    """Verify prompt format invariants across all scenarios."""

    @pytest.mark.parametrize("scenario_name", SCENARIOS.keys())
    async def test_consistent_perspective(self, scenario_name):
        """Prompt should use '# Move N.' or 'Student is playing', never 'You played'."""
        prompt, _ = await _build_prompt_for_scenario(scenario_name)
        assert "You played" not in prompt
        assert "# Student Move" in prompt or "Student is playing" in prompt

    @pytest.mark.parametrize("scenario_name", SCENARIOS.keys())
    async def test_no_per_ply_labels(self, scenario_name):
        """New format should not contain per-ply 'Ply N' labels."""
        prompt, _ = await _build_prompt_for_scenario(scenario_name)
        ply_lines = [l for l in prompt.split("\n") if l.strip().startswith("Ply ")]
        assert len(ply_lines) == 0, f"Found Ply lines in new format:\n{prompt}"

    @pytest.mark.parametrize("scenario_name", SCENARIOS.keys())
    async def test_prompt_length_under_limit(self, scenario_name):
        """Prompt should be concise — under 5000 chars for intermediate profile."""
        prompt, _ = await _build_prompt_for_scenario(scenario_name)
        assert len(prompt) < 5000, (
            f"Prompt is {len(prompt)} chars (limit 5000):\n{prompt}"
        )

    @pytest.mark.parametrize("scenario_name", SCENARIOS.keys())
    async def test_expected_content(self, scenario_name):
        """Prompt contains expected strings and excludes forbidden ones."""
        s = SCENARIOS[scenario_name]
        prompt, _ = await _build_prompt_for_scenario(scenario_name)

        for expected in s["expect_in_prompt"]:
            assert expected in prompt, f"Expected '{expected}' in prompt:\n{prompt}"
        for forbidden in s["expect_not_in_prompt"]:
            assert forbidden not in prompt, f"Forbidden '{forbidden}' found in prompt:\n{prompt}"

    async def test_pin_scenario_has_pin_motif(self):
        """Pin scenario should mention pin in the annotations."""
        prompt, _ = await _build_prompt_for_scenario("pin_and_hanging")
        assert "pin" in prompt.lower(), f"Expected 'pin' in prompt:\n{prompt}"

    async def test_fork_scenario_filters_player_move(self):
        """In missed_fork, Bd3 should not appear as 'Stronger Alternative'."""
        prompt, _ = await _build_prompt_for_scenario("missed_fork")
        assert "Stronger Alternative: Bd3" not in prompt

    async def test_move_header_has_number(self):
        """Move header should use '# Student Move' with numbered move on own line."""
        prompt, _ = await _build_prompt_for_scenario("pin_and_hanging")
        assert "# Student Move" in prompt
        lines = prompt.split("\n")
        assert any(line.strip() == "4. Nc3" for line in lines)
        assert "Move Played" not in prompt

    async def test_good_move_filters_self(self):
        """When student plays the top move, it shouldn't be listed as an alternative."""
        prompt, _ = await _build_prompt_for_scenario("good_move")
        assert "Stronger Alternative: e4" not in prompt


class TestPromptDump:
    """Print full prompts for manual inspection. Run with -s to see output."""

    @pytest.mark.parametrize("scenario_name", SCENARIOS.keys())
    async def test_print_prompt(self, scenario_name, capsys):
        """Dump the generated prompt for human review."""
        s = SCENARIOS[scenario_name]
        prompt, _ = await _build_prompt_for_scenario(scenario_name)

        print(f"\n{'='*60}")
        print(f"SCENARIO: {scenario_name}")
        print(f"  {s['description']}")
        print(f"  FEN: {s['fen']}")
        print(f"  Player move: {s['player_move']}")
        print(f"  Quality: {s['quality']} (cp_loss={s['cp_loss']})")
        print(f"  Prompt length: {len(prompt)} chars")
        print(f"{'='*60}")
        print(prompt)
        print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Live LLM tests — run with: uv run pytest tests/test_coaching_prompts.py -m live -s
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestLiveCoaching:
    """Send prompts to the real LLM and print prompt/response pairs.

    Requires Ollama at https://ollama.st5ve.com/ to be running.
    Run with: uv run pytest tests/test_coaching_prompts.py -m live -s
    """

    @pytest.mark.parametrize("scenario_name", SCENARIOS.keys())
    async def test_llm_response(self, scenario_name):
        """Send a scenario prompt to the LLM and print the pair."""
        s = SCENARIOS[scenario_name]
        prompt, _ = await _build_prompt_for_scenario(scenario_name)

        teacher = _live_teacher()
        response = await teacher.explain_move(prompt)

        print(f"\n{'='*60}")
        print(f"SCENARIO: {scenario_name}")
        print(f"  {s['description']}")
        print(f"  Quality: {s['quality']} (cp_loss={s['cp_loss']})")
        print(f"{'='*60}")
        print(f"PROMPT ({len(prompt)} chars):")
        print(prompt)
        print(f"{'-'*60}")
        print(f"LLM RESPONSE:")
        print(response or "(None — LLM unreachable or failed)")
        print(f"{'='*60}\n")

        # Basic sanity: if the LLM responded, it should be non-empty
        if response is not None:
            assert len(response.strip()) > 0
            # Should not contain markdown formatting
            assert "**" not in response
            assert "##" not in response


# ---------------------------------------------------------------------------
# Integration scenarios — real Stockfish, diverse positions
# ---------------------------------------------------------------------------

EVAL_SCENARIOS = [
    # --- Missed tactics ---
    {
        "name": "missed_knight_fork",
        "desc": "Misses Nxf7 forking king and rook (Fried Liver)",
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p1N1/2B1P3/8/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "student_move": "d2d3",
        "expect_quality": ["blunder", "mistake"],
        "expect_motifs": ["fork"],
    },
    {
        "name": "missed_back_rank_mate",
        "desc": "Misses back rank checkmate Ra8#",
        "fen": "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1",
        "student_move": "a1a7",
        "expect_quality": ["blunder"],
        "expect_motifs": ["checkmate"],
    },
    {
        "name": "missed_mate_in_one",
        "desc": "Misses Qh4# after 1.f3 e5 2.g4??",
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2",
        "student_move": "d7d5",
        "expect_quality": ["blunder"],
        "expect_motifs": ["checkmate"],
    },
    {
        "name": "ignores_mate_threat",
        "desc": "Plays d6 ignoring Qxf7# threat (Scholar's Mate)",
        "fen": "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3",
        "student_move": "d7d6",
        "expect_quality": ["blunder", "mistake"],
        "expect_motifs": [],  # opponent checkmate — may or may not be in prompt
    },
    {
        "name": "missed_free_pawn",
        "desc": "Plays d6 instead of Nxe4 winning a free pawn",
        "fen": "rnbqkb1r/pppppppp/5n2/8/3PP3/8/PPP2PPP/RNBQKBNR b KQkq - 0 2",
        "student_move": "d7d6",
        "expect_quality": ["inaccuracy", "mistake"],
        "expect_motifs": [],
    },
    # --- Good moves ---
    {
        "name": "good_opening_e4",
        "desc": "Plays standard e4 opening",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "student_move": "e2e4",
        "expect_quality": ["good", "brilliant"],
        "expect_motifs": [],
    },
    {
        "name": "good_castling",
        "desc": "Castles kingside for safety in Italian Game",
        "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "student_move": "e1g1",
        "expect_quality": ["good", "brilliant", "inaccuracy"],  # Stockfish may prefer d4/c3
        "expect_motifs": [],
    },
    {
        "name": "good_morphy_defense",
        "desc": "Plays a6 in Ruy Lopez (Morphy Defense)",
        "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        "student_move": "a7a6",
        "expect_quality": ["good", "brilliant"],
        "expect_motifs": [],
    },
    {
        "name": "good_sicilian_nf3",
        "desc": "Plays Nf3 developing in the Sicilian",
        "fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "student_move": "g1f3",
        "expect_quality": ["good", "brilliant"],
        "expect_motifs": [],
    },
    # --- Positional/strategic errors ---
    {
        "name": "walks_into_pin",
        "desc": "Blocks check with Nc3 getting absolutely pinned (1.d4 e5 2.dxe5 Bb4+)",
        "fen": "rnbqk1nr/pppp1ppp/8/4P3/1b6/8/PPP1PPPP/RNBQKBNR w KQkq - 1 3",
        "student_move": "b1c3",
        "expect_quality": ["inaccuracy", "mistake", "blunder"],
        "expect_motifs": ["pin"],
    },
    {
        "name": "passive_bishop_retreat",
        "desc": "Retreats Italian bishop to e2",
        "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 3",
        "student_move": "c4e2",
        "expect_quality": ["inaccuracy", "mistake"],
        "expect_motifs": [],
    },
    {
        "name": "weakening_f_pawn",
        "desc": "Plays f6 weakening king diagonal — blocks Nf6 and allows Ng5",
        "fen": "r1bqkbnr/ppp2ppp/2np4/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 2 3",
        "student_move": "f7f6",
        "expect_quality": ["inaccuracy", "mistake", "blunder"],
        "expect_motifs": [],
    },
    # --- Endgame ---
    {
        "name": "endgame_wrong_king",
        "desc": "Moves king away from passed pawn instead of supporting it",
        "fen": "8/8/8/8/3Pk3/8/3K4/8 w - - 0 1",
        "student_move": "d2c2",
        "expect_quality": ["good", "inaccuracy", "mistake"],
        "expect_motifs": [],
    },
    {
        "name": "endgame_good_pawn_push",
        "desc": "Pushes passed pawn in a favorable K+P ending",
        "fen": "8/8/8/8/4k3/8/3PK3/8 w - - 0 1",
        "student_move": "d2d4",
        "expect_quality": ["good", "brilliant", "inaccuracy"],
        "expect_motifs": [],
    },
    # --- Middlegame complexity ---
    {
        "name": "trade_queens_when_ahead",
        "desc": "Trades queens when materially ahead",
        "fen": "r1b2rk1/ppp2ppp/2n5/3qN3/8/8/PPPQ1PPP/R1B2RK1 w - - 0 10",
        "student_move": "d2d5",
        "expect_quality": ["good", "brilliant", "inaccuracy"],
        "expect_motifs": [],
    },

    # ===================================================================
    # Wave 2: broader coverage — d4 games, Sicilian, endgame, tactics
    # ===================================================================

    # --- Queen's pawn good moves ---
    {
        "name": "good_qga_accept",
        "desc": "Accepts Queen's Gambit — perfectly sound opening choice",
        "fen": "rnbqkbnr/ppp1pppp/8/3p4/2PP4/8/PP2PPPP/RNBQKBNR b KQkq - 0 2",
        "student_move": "d5c4",
        "expect_quality": ["good", "brilliant", "inaccuracy"],
        "expect_motifs": [],
    },
    {
        "name": "good_london_develop",
        "desc": "Plays Bf4 in the London System — signature developing move",
        "fen": "rnbqkb1r/ppp1pppp/5n2/3p4/3P4/5N2/PPP1PPPP/RNBQKB1R w KQkq - 2 3",
        "student_move": "c1f4",
        "expect_quality": ["good", "brilliant", "inaccuracy"],
        "expect_motifs": [],
    },
    # --- Piece placement errors ---
    {
        "name": "premature_queen_sortie",
        "desc": "Brings queen out early to e7 blocking bishop development",
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
        "student_move": "d8e7",
        "expect_quality": ["inaccuracy", "mistake"],
        "expect_motifs": [],
    },
    {
        "name": "knight_on_the_rim",
        "desc": "Plays Na4 sending knight to the rim with no purpose",
        "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 4",
        "student_move": "c3a4",
        "expect_quality": ["inaccuracy", "mistake", "blunder"],
        "expect_motifs": [],
    },
    # --- Sicilian middlegame ---
    {
        "name": "sicilian_passive_bishop",
        "desc": "Plays passive Be2 in Open Sicilian when Bg5/Bc4/Be3 are stronger",
        "fen": "rnbqkb1r/1p2pppp/p2p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6",
        "student_move": "f1e2",
        "expect_quality": ["good", "inaccuracy", "mistake"],
        "expect_motifs": [],
    },
    # --- Tactical blunders ---
    {
        "name": "premature_sacrifice",
        "desc": "Sacrifices bishop on f7+ with no follow-up — loses piece for pawn",
        "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 3",
        "student_move": "c4f7",
        "expect_quality": ["blunder", "mistake"],
        "expect_motifs": [],
    },
    {
        "name": "falls_for_legals_mate",
        "desc": "Greedily captures queen — walks into Legal's Mate pattern",
        "fen": "rn1qkbnr/ppp2p1p/3p2p1/4N3/2B1P1b1/2N5/PPPP1PPP/R1BQK2R b KQkq - 0 5",
        "student_move": "g4d1",
        "expect_quality": ["blunder", "mistake"],
        "expect_motifs": [],
    },
    # --- KID thematic play ---
    {
        "name": "good_kid_d5_break",
        "desc": "Plays thematic d5 central break in King's Indian Defense",
        "fen": "r1bq1rk1/pppn1pbp/3ppnp1/8/2PPP3/2N2N2/PP2BPPP/R1BQ1RK1 b - - 0 8",
        "student_move": "d6d5",
        "expect_quality": ["good", "brilliant", "inaccuracy", "mistake"],
        "expect_motifs": [],
    },
    # --- Rook ending ---
    {
        "name": "good_rook_cut_off_king",
        "desc": "Cuts off enemy king along the 6th rank — textbook technique",
        "fen": "8/8/4k3/8/2R5/5K2/4P3/8 w - - 0 1",
        "student_move": "c4c6",
        "expect_quality": ["good", "brilliant", "inaccuracy"],
        "expect_motifs": [],
    },
    # --- Other openings ---
    {
        "name": "good_caro_kann_bf5",
        "desc": "Develops bishop to f5 in the Caro-Kann — classical and strong",
        "fen": "rnbqkbnr/pp2pppp/2p5/3pP3/3P4/8/PPP2PPP/RNBQKBNR b KQkq - 0 3",
        "student_move": "c8f5",
        "expect_quality": ["good", "brilliant", "inaccuracy"],
        "expect_motifs": [],
    },
    {
        "name": "good_scandinavian_qd6",
        "desc": "Retreats queen to d6 in Scandinavian — solid modern main line",
        "fen": "rnb1kbnr/ppp1pppp/8/3q4/8/2N5/PPPP1PPP/R1BQKBNR b KQkq - 1 3",
        "student_move": "d5d6",
        "expect_quality": ["good", "brilliant", "inaccuracy", "mistake"],
        "expect_motifs": [],
    },
]


async def _build_eval_scenario(scenario: dict) -> dict:
    """Run full pipeline with real Stockfish for an eval scenario."""
    board = chess.Board(scenario["fen"])
    student_uci = scenario["student_move"]
    move = chess.Move.from_uci(student_uci)
    assert move in board.legal_moves, f"Illegal move {student_uci} in {scenario['name']}"

    student_san = board.san(move)
    profile = get_profile("intermediate")
    engine = EngineAnalysis(hash_mb=64)

    try:
        await engine.start()
        eval_before = await engine.evaluate(scenario["fen"], depth=16)
        tree = await build_coaching_tree(engine, board, student_uci, eval_before, profile)

        # Eval after student's move for cp loss
        temp = board.copy()
        temp.push(move)
        eval_after = await engine.evaluate(temp.fen(), depth=16)

        cp_before = _cp_value(eval_before)
        cp_after = _cp_value(eval_after)
        if board.turn == chess.WHITE:
            cp_loss = cp_before - cp_after
        else:
            cp_loss = cp_after - cp_before
        cp_loss = max(0, cp_loss)

        is_best = student_uci == (eval_before.best_move or "")
        quality = _classify_move(cp_loss, is_best, position_is_sharp=False)

        prompt = serialize_report(
            tree,
            quality=quality.value,
            cp_loss=cp_loss,
        )

        best_san = "?"
        if eval_before.best_move:
            try:
                best_san = board.san(chess.Move.from_uci(eval_before.best_move))
            except Exception:
                best_san = eval_before.best_move

        return {
            "scenario": scenario,
            "student_san": student_san,
            "best_san": best_san,
            "quality": quality.value,
            "cp_loss": cp_loss,
            "prompt": prompt,
            "tree": tree,
        }
    finally:
        await engine.stop()


@pytest.fixture(scope="module")
def _engine_results(request):
    """Cache to avoid re-running Stockfish for the same scenario in one module."""
    return {}


@pytest.mark.integration
class TestEvalScenarios:
    """Integration tests with real Stockfish across diverse scenarios.

    Run with: uv run pytest tests/test_coaching_prompts.py -m integration -s
    """

    @pytest.mark.parametrize(
        "scenario",
        EVAL_SCENARIOS,
        ids=[s["name"] for s in EVAL_SCENARIOS],
    )
    async def test_move_quality_classification(self, scenario):
        """Engine classifies the move quality within expected range."""
        result = await _build_eval_scenario(scenario)
        assert result["quality"] in scenario["expect_quality"], (
            f"{scenario['name']}: expected quality in {scenario['expect_quality']}, "
            f"got {result['quality']} (cp_loss={result['cp_loss']})"
        )

    @pytest.mark.parametrize(
        "scenario",
        EVAL_SCENARIOS,
        ids=[s["name"] for s in EVAL_SCENARIOS],
    )
    async def test_prompt_contains_expected_motifs(self, scenario):
        """Prompt mentions expected tactical motifs when present."""
        result = await _build_eval_scenario(scenario)
        prompt_lower = result["prompt"].lower()
        for motif in scenario["expect_motifs"]:
            assert motif in prompt_lower, (
                f"{scenario['name']}: expected '{motif}' in prompt:\n{result['prompt']}"
            )

    @pytest.mark.parametrize(
        "scenario",
        EVAL_SCENARIOS,
        ids=[s["name"] for s in EVAL_SCENARIOS],
    )
    async def test_prompt_structure_invariants(self, scenario):
        """Prompt follows structural rules regardless of position."""
        result = await _build_eval_scenario(scenario)
        prompt = result["prompt"]

        # Always uses third person
        assert "You played" not in prompt
        assert "# Move " in prompt or "Student is playing" in prompt

        # Good moves should not have "Stronger Alternative"
        if result["quality"] in ("good", "brilliant"):
            assert "Stronger Alternative" not in prompt

        # Length sanity
        assert len(prompt) < 8000, f"Prompt too long: {len(prompt)} chars"

    @pytest.mark.parametrize(
        "scenario",
        EVAL_SCENARIOS,
        ids=[s["name"] for s in EVAL_SCENARIOS],
    )
    async def test_dump_prompt(self, scenario, capsys):
        """Print prompt for human review. Run with -s flag."""
        result = await _build_eval_scenario(scenario)
        print(f"\n{'='*60}")
        print(f"SCENARIO: {scenario['name']} — {scenario['desc']}")
        print(f"  Student: {result['student_san']}  Best: {result['best_san']}")
        print(f"  Quality: {result['quality']}  CP loss: {result['cp_loss']}")
        print(f"  Prompt length: {len(result['prompt'])} chars")
        print(f"{'='*60}")
        print(result["prompt"])
        print(f"{'='*60}\n")


@pytest.mark.live
class TestEvalScenariosLive:
    """Send eval scenario prompts to real LLM. Run with -m live -s."""

    @pytest.mark.parametrize(
        "scenario",
        EVAL_SCENARIOS,
        ids=[s["name"] for s in EVAL_SCENARIOS],
    )
    async def test_llm_response(self, scenario):
        """Full pipeline: Stockfish + LLM for each scenario."""
        result = await _build_eval_scenario(scenario)
        teacher = _live_teacher()
        response = await teacher.explain_move(result["prompt"])

        print(f"\n{'='*60}")
        print(f"SCENARIO: {scenario['name']} — {scenario['desc']}")
        print(f"  Student: {result['student_san']}  Best: {result['best_san']}")
        print(f"  Quality: {result['quality']}  CP loss: {result['cp_loss']}")
        print(f"{'='*60}")
        print(f"PROMPT ({len(result['prompt'])} chars):")
        print(result["prompt"])
        print(f"{'-'*60}")
        print(f"LLM RESPONSE:")
        print(response or "(None — LLM unreachable)")
        print(f"{'='*60}\n")

        if response is not None:
            assert len(response.strip()) > 0
            assert "**" not in response
            assert "##" not in response
