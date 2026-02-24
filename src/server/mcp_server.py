"""MCP server that exposes chess coaching as a tool."""

from __future__ import annotations

import asyncio
import json
import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chess-coach")


@mcp.tool()
async def analyze_move(
    fen: str,
    move: str,
    elo_profile: str = "intermediate",
    no_llm: bool = False,
) -> str:
    """Analyze a chess move and return coaching advice.

    Args:
        fen: Position FEN string.
        move: Student move in SAN (e.g. "Nf3") or UCI (e.g. "g1f3") notation.
        elo_profile: One of beginner, intermediate, advancing, club, competitive.
        no_llm: If true, skip the LLM call and return only the generated prompt.

    Returns:
        JSON with updated_fen, prompt, and advice.
    """
    cmd = [
        sys.executable, "-m", "server.cli",
        fen, move,
        "--elo-profile", elo_profile,
    ]
    if no_llm:
        cmd.append("--no-llm")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        return json.dumps({"error": stderr.decode().strip()})

    return stdout.decode()


if __name__ == "__main__":
    mcp.run()
