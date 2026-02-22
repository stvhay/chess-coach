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
from server.llm import ChessTeacher, format_coaching_prompt
from server.screener import screen_and_validate


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
        "name": "weakening_h_pawn",
        "desc": "Pushes h6 weakening kingside pawn shield after castling",
        "fen": "r1bq1rk1/pppnbppp/4pn2/3p4/2PP4/2NBPN2/PP3PPP/R1BQ1RK1 b - - 0 8",
        "student_move": "h7h6",
    },

    # --- Endgame ---
    {
        "name": "endgame_wrong_king",
        "desc": "Moves king sideways instead of toward the center in K+P ending",
        "fen": "8/8/8/4k3/8/4K3/3P4/8 w - - 0 1",
        "student_move": "e3f3",
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
    ctx = await screen_and_validate(engine, board, student_uci, eval_before, profile)

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

    ctx.quality = quality.value
    ctx.cp_loss = cp_loss
    ctx.player_color = "White" if board.turn == chess.WHITE else "Black"

    # Generate prompt
    prompt = format_coaching_prompt(ctx)

    # Get LLM response
    response = await teacher.explain_move(prompt)

    best_san = "?"
    if eval_before.best_move:
        try:
            best_san = board.san(chess.Move.from_uci(eval_before.best_move))
        except Exception:
            best_san = eval_before.best_move

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
        "num_alternatives": len(
            [l for l in ctx.best_lines if l.first_move_uci != student_uci]
        ),
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
