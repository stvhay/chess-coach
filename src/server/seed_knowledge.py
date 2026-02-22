"""CLI script to seed the knowledge base.

Usage: python -m server.seed_knowledge
"""

from __future__ import annotations

import asyncio
import os

from server.knowledge import seed_knowledge_base
from server.rag import ChessRAG


async def main() -> None:
    data_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "knowledge_base.json")
    rag = ChessRAG(
        ollama_url=os.environ.get("OLLAMA_URL", "https://ollama.st5ve.com"),
        persist_dir=os.environ.get("CHROMADB_DIR", "data/chromadb"),
    )
    await rag.start()
    count = await seed_knowledge_base(rag, data_path)
    print(f"Seeded {count} knowledge chunks.")


if __name__ == "__main__":
    asyncio.run(main())
