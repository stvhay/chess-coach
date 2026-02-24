"""CLI script to seed the knowledge base.

Usage: python -m server.seed_knowledge
"""

from __future__ import annotations

import asyncio
import os

from server.config import Settings
from server.knowledge import seed_knowledge_base
from server.rag import ChessRAG


async def main() -> None:
    settings = Settings()
    data_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "knowledge_base.json")
    rag = ChessRAG(
        base_url=settings.effective_embed_base_url,
        model=settings.embed_model,
        api_key=settings.effective_embed_api_key,
        persist_dir=settings.chromadb_dir,
    )
    await rag.start()
    count = await seed_knowledge_base(rag, data_path)
    print(f"Seeded {count} knowledge chunks.")


if __name__ == "__main__":
    asyncio.run(main())
