import os

import pytest
from unittest.mock import AsyncMock
from server.config import Settings
from server.rag import ChessRAG, Chunk, Result


# Deterministic fake embeddings for testing
def fake_embed(texts: list[str]) -> list[list[float]]:
    """Generate deterministic fake embeddings based on text length."""
    return [[float(len(t) % 10) / 10.0] * 768 for t in texts]


@pytest.fixture
async def rag(tmp_path):
    r = ChessRAG(
        base_url="http://fake:11434",
        model="nomic-embed-text",
        persist_dir=str(tmp_path / "chromadb"),
    )
    # Mock the embedding call
    r._embed = AsyncMock(side_effect=fake_embed)
    await r.start()
    yield r


async def test_ingest_and_query(rag):
    chunks = [
        Chunk(
            id="pos_001",
            text="Sicilian Najdorf with e5 pawn break. Black has strong center control.",
            metadata={"opening": "sicilian", "eco": "B90"},
        ),
        Chunk(
            id="pos_002",
            text="French Defense advance variation. White has space advantage on kingside.",
            metadata={"opening": "french", "eco": "C02"},
        ),
    ]
    await rag.ingest(chunks)
    results = await rag.query("Sicilian pawn center", n=2)
    assert len(results) >= 1
    assert all(isinstance(r, Result) for r in results)
    assert results[0].id in ("pos_001", "pos_002")
    assert results[0].text is not None
    assert results[0].metadata is not None


async def test_ingest_and_delete(rag):
    chunks = [
        Chunk(id="del_001", text="Test chunk to delete", metadata={}),
    ]
    await rag.ingest(chunks)
    results = await rag.query("Test chunk", n=1)
    assert len(results) == 1
    await rag.delete(["del_001"])
    results = await rag.query("Test chunk", n=1)
    assert len(results) == 0


async def test_query_with_filter(rag):
    chunks = [
        Chunk(id="f_001", text="King's Indian Defense fianchetto", metadata={"opening": "kings_indian"}),
        Chunk(id="f_002", text="Queen's Gambit Declined", metadata={"opening": "qgd"}),
    ]
    await rag.ingest(chunks)
    results = await rag.query("fianchetto", n=2, filters={"opening": "kings_indian"})
    assert len(results) >= 1
    assert results[0].metadata["opening"] == "kings_indian"


async def test_query_empty_store(rag):
    results = await rag.query("anything", n=5)
    assert results == []


@pytest.mark.integration
async def test_real_ollama_embedding():
    """Integration test — requires an OpenAI-compatible embedding endpoint."""
    settings = Settings()
    rag = ChessRAG(
        base_url=settings.effective_embed_base_url,
        model=settings.embed_model,
        api_key=settings.effective_embed_api_key,
        persist_dir=None,  # in-memory only
    )
    await rag.start()
    chunks = [
        Chunk(id="int_001", text="Isolated queen pawn in the middlegame", metadata={}),
    ]
    await rag.ingest(chunks)
    results = await rag.query("weak d-pawn", n=1)
    assert len(results) == 1
    assert results[0].id == "int_001"
