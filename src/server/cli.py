"""CLI utility for single-position coaching analysis.

Usage:
    python -m server.cli <fen> <move> [--prompt-override FILE]
        [--elo-profile NAME] [--ollama-url URL] [--model MODEL]
        [--no-llm] [--stockfish PATH]

Returns JSON with updated_fen, prompt, and advice.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import chess

from server.coach import assess_move
from server.elo_profiles import DEFAULT_PROFILE, ELO_PROFILES, get_profile
from server.engine import EngineAnalysis
from server.game_tree import build_coaching_tree
from server.llm import ChessTeacher
from server.report import serialize_report


async def _run(args: argparse.Namespace) -> dict:
    board = chess.Board(args.fen)

    # Parse move — accept SAN or UCI
    try:
        move = board.parse_san(args.move)
    except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError):
        move = chess.Move.from_uci(args.move)
    if move not in board.legal_moves:
        print(f"error: {args.move} is not legal in this position", file=sys.stderr)
        sys.exit(1)

    player_move_uci = move.uci()

    # Engine
    engine = EngineAnalysis(stockfish_path=args.stockfish)
    await engine.start()
    try:
        eval_before = await engine.evaluate(board.fen(), depth=get_profile(args.elo_profile).validate_depth)

        # Assess move quality
        board_before = board.copy()
        board.push(move)
        eval_after = await engine.evaluate(board.fen(), depth=get_profile(args.elo_profile).validate_depth)

        best_move_uci = eval_before.best_move or player_move_uci
        coaching = assess_move(
            board_before=board_before,
            board_after=board.copy(),
            player_move_uci=player_move_uci,
            eval_before=eval_before,
            eval_after=eval_after,
            best_move_uci=best_move_uci,
        )

        # Quality / severity for the report
        quality = coaching.quality.value if coaching else "good"
        cp_loss = coaching.severity if coaching else 0

        # Build coaching tree from the pre-move board
        profile = get_profile(args.elo_profile)
        tree = await build_coaching_tree(
            engine, board_before, player_move_uci, eval_before, profile
        )
    finally:
        await engine.stop()

    # Serialize report (or use prompt override)
    if args.prompt_override:
        with open(args.prompt_override) as f:
            prompt = f.read()
    else:
        prompt = serialize_report(tree, quality=quality, cp_loss=cp_loss)

    # LLM
    advice = None
    if not args.no_llm:
        teacher = ChessTeacher(
            ollama_url=args.ollama_url,
            model=args.model,
            system_prompt=args.system_prompt_text,
        )
        advice = await teacher.explain_move(prompt)

    updated_fen = board.fen()
    return {
        "updated_fen": updated_fen,
        "prompt": prompt,
        "advice": advice,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Single-position coaching analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("fen", help="Position FEN (quote the full string)")
    parser.add_argument("move", help="Student move in SAN or UCI notation")
    parser.add_argument(
        "--prompt-override", metavar="FILE",
        help="Read LLM prompt from FILE instead of generating one",
    )
    parser.add_argument(
        "--system-prompt", metavar="FILE", dest="system_prompt_file",
        help="Read LLM system prompt from FILE",
    )
    parser.add_argument(
        "--elo-profile", default=DEFAULT_PROFILE,
        choices=list(ELO_PROFILES),
        help=f"Analysis profile (default: {DEFAULT_PROFILE})",
    )
    parser.add_argument(
        "--ollama-url", default="https://ollama.st5ve.com",
        help="Ollama API base URL",
    )
    parser.add_argument(
        "--model", default="qwen2.5:14b",
        help="Ollama model name",
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip LLM call; return prompt only",
    )
    parser.add_argument(
        "--stockfish", default="stockfish",
        help="Path to Stockfish binary",
    )
    args = parser.parse_args()

    # Load system prompt override if provided
    args.system_prompt_text = None
    if args.system_prompt_file:
        with open(args.system_prompt_file) as f:
            args.system_prompt_text = f.read()

    result = asyncio.run(_run(args))
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
