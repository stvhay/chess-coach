#!/usr/bin/env python3
"""Evaluate coaching prompt + LLM response quality across diverse positions.

Usage:
    uv run python tests/eval_coaching.py                    # all scenarios
    uv run python tests/eval_coaching.py --batch 0 --size 5 # first 5
    uv run python tests/eval_coaching.py --batch 1 --size 5 # next 5
"""

import argparse
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import chess

from server.coach import _classify_move, _cp_value, MoveQuality
from server.elo_profiles import get_profile
from server.engine import EngineAnalysis
from server.game_tree import build_coaching_tree
from server.llm import ChessTeacher
from server.report import serialize_report


# ---------------------------------------------------------------------------
# Scenario definitions: diverse positions covering tactical themes, move
# qualities (blunder/mistake/inaccuracy/good), and game phases.
# ---------------------------------------------------------------------------

SCENARIOS = [
    # --- Missed tactics ---
    {
        "name": "missed_knight_fork",
        "desc": "Misses Nxf7 forking king and rook (Fried Liver)",
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p1N1/2B1P3/8/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "student_move": "d2d3",
    },
    {
        "name": "missed_back_rank_mate",
        "desc": "Misses back rank checkmate Ra8#",
        "fen": "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1",
        "student_move": "a1a7",
    },
    {
        "name": "missed_mate_in_one",
        "desc": "Misses Qh4# after 1.f3 e5 2.g4??",
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2",
        "student_move": "d7d5",
    },
    {
        "name": "ignores_mate_threat",
        "desc": "Plays d6 ignoring Qxf7# threat (Scholar's Mate)",
        "fen": "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3",
        "student_move": "d7d6",
    },
    {
        "name": "missed_free_pawn",
        "desc": "Plays d6 instead of Nxe4 winning a free pawn",
        "fen": "rnbqkb1r/pppppppp/5n2/8/3PP3/8/PPP2PPP/RNBQKBNR b KQkq - 0 2",
        "student_move": "d7d6",
    },

    # --- Good moves ---
    {
        "name": "good_opening_e4",
        "desc": "Plays standard e4 opening — engine's top choice",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "student_move": "e2e4",
    },
    {
        "name": "good_castling",
        "desc": "Castles kingside for safety in Italian Game",
        "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "student_move": "e1g1",
    },
    {
        "name": "good_morphy_defense",
        "desc": "Plays a6 in Ruy Lopez (Morphy Defense) — solid book move",
        "fen": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        "student_move": "a7a6",
    },
    {
        "name": "good_sicilian_nf3",
        "desc": "Plays Nf3 developing in the Sicilian — principled",
        "fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "student_move": "g1f3",
    },

    # --- Positional/strategic errors ---
    {
        "name": "walks_into_pin",
        "desc": "Blocks check with Nc3 getting absolutely pinned (1.d4 e5 2.dxe5 Bb4+)",
        "fen": "rnbqk1nr/pppp1ppp/8/4P3/1b6/8/PPP1PPPP/RNBQKBNR w KQkq - 1 3",
        "student_move": "b1c3",
    },
    {
        "name": "passive_bishop_retreat",
        "desc": "Retreats Italian bishop to e2 instead of keeping active diagonal",
        "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 3",
        "student_move": "c4e2",
    },
    {
        "name": "weakening_f_pawn",
        "desc": "Plays f6 weakening king diagonal — blocks Nf6 and allows Ng5",
        "fen": "r1bqkbnr/ppp2ppp/2np4/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 2 3",
        "student_move": "f7f6",
    },

    # --- Endgame ---
    {
        "name": "endgame_wrong_king",
        "desc": "Moves king away from passed pawn instead of supporting it",
        "fen": "8/8/8/8/3Pk3/8/3K4/8 w - - 0 1",
        "student_move": "d2c2",
    },
    {
        "name": "endgame_good_pawn_push",
        "desc": "Pushes passed pawn in a favorable K+P ending",
        "fen": "8/8/8/8/4k3/8/3PK3/8 w - - 0 1",
        "student_move": "d2d4",
    },

    # --- Middlegame complexity ---
    {
        "name": "trade_queens_when_ahead",
        "desc": "Trades queens when materially ahead — simplifying correctly",
        "fen": "r1b2rk1/ppp2ppp/2n5/3qN3/8/8/PPPQ1PPP/R1B2RK1 w - - 0 10",
        "student_move": "d2d5",
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
    },
    {
        "name": "good_london_develop",
        "desc": "Plays Bf4 in the London System — signature developing move",
        "fen": "rnbqkb1r/ppp1pppp/5n2/3p4/3P4/5N2/PPP1PPPP/RNBQKB1R w KQkq - 2 3",
        "student_move": "c1f4",
    },

    # --- Piece placement errors ---
    {
        "name": "premature_queen_sortie",
        "desc": "Brings queen out early to e7 blocking bishop development",
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
        "student_move": "d8e7",
    },
    {
        "name": "knight_on_the_rim",
        "desc": "Plays Na4 sending knight to the rim with no purpose",
        "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 4",
        "student_move": "c3a4",
    },

    # --- Sicilian middlegame ---
    {
        "name": "sicilian_passive_bishop",
        "desc": "Plays passive Be2 in Open Sicilian when Bg5/Bc4/Be3 are stronger",
        "fen": "rnbqkb1r/1p2pppp/p2p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6",
        "student_move": "f1e2",
    },

    # --- Tactical blunders ---
    {
        "name": "premature_sacrifice",
        "desc": "Sacrifices bishop on f7+ with no follow-up — loses piece for pawn",
        "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 3",
        "student_move": "c4f7",
    },
    {
        "name": "falls_for_legals_mate",
        "desc": "Greedily captures queen — walks into Legal's Mate pattern",
        "fen": "rn1qkbnr/ppp2p1p/3p2p1/4N3/2B1P1b1/2N5/PPPP1PPP/R1BQK2R b KQkq - 0 5",
        "student_move": "g4d1",
    },

    # --- KID thematic play ---
    {
        "name": "good_kid_d5_break",
        "desc": "Plays thematic d5 central break in King's Indian Defense",
        "fen": "r1bq1rk1/pppn1pbp/3ppnp1/8/2PPP3/2N2N2/PP2BPPP/R1BQ1RK1 b - - 0 8",
        "student_move": "d6d5",
    },

    # --- Rook ending ---
    {
        "name": "good_rook_cut_off_king",
        "desc": "Cuts off enemy king along the 6th rank — textbook technique",
        "fen": "8/8/4k3/8/2R5/5K2/4P3/8 w - - 0 1",
        "student_move": "c4c6",
    },

    # --- Other openings ---
    {
        "name": "good_caro_kann_bf5",
        "desc": "Develops bishop to f5 in the Caro-Kann — classical and strong",
        "fen": "rnbqkbnr/pp2pppp/2p5/3pP3/3P4/8/PPP2PPP/RNBQKBNR b KQkq - 0 3",
        "student_move": "c8f5",
    },
    {
        "name": "good_scandinavian_qd6",
        "desc": "Retreats queen to d6 in Scandinavian — solid modern main line",
        "fen": "rnb1kbnr/ppp1pppp/8/3q4/8/2N5/PPPP1PPP/R1BQKBNR b KQkq - 1 3",
        "student_move": "d5d6",
    },
]


async def evaluate_scenario(engine, teacher, scenario, profile):
    """Run the full coaching pipeline and return structured result."""
    board = chess.Board(scenario["fen"])
    student_uci = scenario["student_move"]

    # Verify the move is legal
    try:
        move = chess.Move.from_uci(student_uci)
        if move not in board.legal_moves:
            return {"name": scenario["name"], "error": f"Illegal move: {student_uci}"}
    except ValueError as e:
        return {"name": scenario["name"], "error": str(e)}

    student_san = board.san(move)

    # Get eval before the student's move
    eval_before = await engine.evaluate(scenario["fen"], depth=16)

    # Run the coaching pipeline
    tree = await build_coaching_tree(engine, board, student_uci, eval_before, profile)

    # Determine move quality from eval difference
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

    # Generate prompt
    prompt = serialize_report(
        tree,
        quality=quality.value,
        cp_loss=cp_loss,
    )

    # Get LLM response
    response = await teacher.explain_move(prompt)

    best_san = "?"
    if eval_before.best_move:
        try:
            best_san = board.san(chess.Move.from_uci(eval_before.best_move))
        except Exception:
            best_san = eval_before.best_move

    alts = tree.alternatives()
    player_node = tree.player_move_node()
    player_uci = player_node.move.uci() if player_node and player_node.move else ""

    return {
        "name": scenario["name"],
        "desc": scenario["desc"],
        "fen": scenario["fen"],
        "student_move_san": student_san,
        "student_move_uci": student_uci,
        "best_move_san": best_san,
        "best_move_uci": eval_before.best_move,
        "quality": quality.value,
        "cp_loss": cp_loss,
        "eval_before_cp": eval_before.score_cp,
        "eval_before_mate": eval_before.score_mate,
        "prompt": prompt,
        "prompt_length": len(prompt),
        "response": response,
        "num_alternatives": len([a for a in alts if a.move.uci() != player_uci]),
    }


async def run_batch(scenarios, profile_name="intermediate"):
    """Run a batch of scenarios and return results."""
    engine = EngineAnalysis(hash_mb=64)
    teacher = ChessTeacher()
    profile = get_profile(profile_name)
    results = []

    try:
        await engine.start()
        for s in scenarios:
            try:
                result = await evaluate_scenario(engine, teacher, s, profile)
                results.append(result)
            except Exception as e:
                results.append({"name": s["name"], "error": str(e)})
    finally:
        await engine.stop()

    return results


def print_results(results):
    """Print formatted evaluation results."""
    for r in results:
        print(f"\n{'='*70}")
        if "error" in r:
            print(f"SCENARIO: {r['name']} — ERROR: {r['error']}")
            continue

        print(f"SCENARIO: {r['name']}")
        print(f"  {r['desc']}")
        print(f"  Student: {r['student_move_san']}  Best: {r['best_move_san']}")
        print(f"  Quality: {r['quality']}  CP loss: {r['cp_loss']}")
        print(f"  Eval before: cp={r['eval_before_cp']} mate={r['eval_before_mate']}")
        print(f"  Alternatives shown: {r['num_alternatives']}")
        print(f"  Prompt length: {r['prompt_length']} chars")
        print(f"{'='*70}")
        print(f"PROMPT:")
        print(r["prompt"])
        print(f"{'-'*70}")
        print(f"LLM RESPONSE:")
        print(r["response"] or "(None — LLM unreachable)")
        print(f"{'='*70}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate coaching quality")
    parser.add_argument("--batch", type=int, default=None, help="Batch index (0-based)")
    parser.add_argument("--size", type=int, default=5, help="Batch size")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of formatted text")
    args = parser.parse_args()

    if args.batch is not None:
        start = args.batch * args.size
        end = start + args.size
        scenarios = SCENARIOS[start:end]
    else:
        scenarios = SCENARIOS

    results = asyncio.run(run_batch(scenarios))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_results(results)


if __name__ == "__main__":
    main()
