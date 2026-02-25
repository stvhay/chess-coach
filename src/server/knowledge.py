"""Knowledge base query construction and RAG integration.

Builds semantic queries from position analysis and formats RAG results
for inclusion in LLM prompts. Gracefully degrades on any failure.
"""

from __future__ import annotations

import json
from pathlib import Path

from server.analysis import PositionReport
from server.rag import ChessRAG, Chunk, Result


def build_rag_query(
    report: PositionReport,
    coaching_quality: str,
    tactics_summary: str = "",
) -> str:
    """Build a semantic search query from position analysis.

    Blunder/mistake: focus on tactical themes present.
    Inaccuracy: focus on positional concepts.
    Brilliant: focus on the theme the student found.
    """
    parts: list[str] = []

    if coaching_quality in ("blunder", "mistake"):
        # Tactical focus
        if tactics_summary:
            parts.append(tactics_summary)
        else:
            # Fall back to motif names from the report
            motifs = report.tactics
            if motifs.forks:
                parts.append("knight fork tactics")
            if motifs.pins:
                parts.append("pin tactics")
            if motifs.skewers:
                parts.append("skewer tactics")
            if motifs.hanging:
                parts.append("hanging piece undefended")
            if motifs.discovered_attacks:
                parts.append("discovered attack")
            if not parts:
                parts.append("tactical awareness calculation")

    elif coaching_quality == "inaccuracy":
        # Positional focus
        ps = report.pawn_structure
        if any(p.is_isolated for p in ps.white) or any(p.is_isolated for p in ps.black):
            parts.append("isolated pawn weakness")
        if any(p.is_passed for p in ps.white) or any(p.is_passed for p in ps.black):
            parts.append("passed pawn advantage")
        if abs(report.material.imbalance) >= 1:
            parts.append("material imbalance")
        if report.activity.white_total_mobility - report.activity.black_total_mobility > 10:
            parts.append("piece activity mobility")
        if not parts:
            parts.append("positional understanding strategy")

    elif coaching_quality == "brilliant":
        # Focus on what the student found
        if tactics_summary:
            parts.append(tactics_summary)
        else:
            parts.append("brilliant tactical combination")

    else:
        parts.append("chess improvement general concepts")

    return " ".join(parts)[:200]  # Cap query length


def format_rag_results(results: list[Result]) -> str:
    """Concatenate top results with clear delimiters.

    Returns empty string if no results.
    """
    if not results:
        return ""
    sections = []
    for r in results:
        theme = r.metadata.get("theme", "general") if r.metadata else "general"
        sections.append(f"[{theme}] {r.text}")
    return "\n---\n".join(sections)


async def query_knowledge(
    rag: ChessRAG,
    report: PositionReport,
    coaching_quality: str,
    tactics_summary: str = "",
    n: int = 3,
) -> str:
    """Build query, search RAG, format results. Returns "" on any failure.

    If n=0, returns empty string immediately (RAG disabled).
    """
    if n <= 0:
        return ""
    try:
        query = build_rag_query(report, coaching_quality, tactics_summary)
        results = await rag.query(query, n=n)
        return format_rag_results(results)
    except Exception:
        return ""


async def seed_knowledge_base(rag: ChessRAG, data_path: str) -> int:
    """Load JSON knowledge chunks and ingest into RAG.

    Idempotent via deterministic IDs in the JSON data.
    Returns the number of chunks ingested.
    """
    path = Path(data_path)
    with path.open() as f:
        data = json.load(f)

    chunks = [
        Chunk(
            id=item["id"],
            text=item["text"],
            metadata=item.get("metadata", {}),
        )
        for item in data
    ]

    if chunks:
        await rag.ingest(chunks)

    return len(chunks)
