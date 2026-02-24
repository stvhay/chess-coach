"""RAG (Retrieval-Augmented Generation) for chess knowledge.

Uses an OpenAI-compatible embedding API (Ollama /v1/embeddings,
Together, OpenAI, etc.) and ChromaDB for vector storage.
"""

from dataclasses import dataclass
import chromadb
import httpx


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict


@dataclass
class Result:
    id: str
    text: str
    metadata: dict
    distance: float


class ChessRAG:
    def __init__(
        self,
        base_url: str,
        model: str = "nomic-embed-text",
        api_key: str | None = None,
        persist_dir: str | None = None,
        collection_name: str = "chess_knowledge",
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._client: chromadb.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None

    async def start(self):
        if self._persist_dir:
            self._client = chromadb.PersistentClient(path=self._persist_dir)
        else:
            self._client = chromadb.Client()
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI-compatible /v1/embeddings endpoint."""
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/v1/embeddings",
                json={"model": self._model, "input": texts},
                headers=headers,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return [d["embedding"] for d in data["data"]]

    async def ingest(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        if self._collection is None:
            raise RuntimeError("RAG not started. Call start() first.")
        texts = [c.text for c in chunks]
        embeddings = await self._embed(texts)
        # ChromaDB rejects empty metadata dicts; convert to None
        metadatas = [c.metadata if c.metadata else None for c in chunks]
        self._collection.upsert(
            ids=[c.id for c in chunks],
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

    async def query(
        self, text: str, n: int = 5, filters: dict | None = None
    ) -> list[Result]:
        if self._collection is None:
            raise RuntimeError("RAG not started. Call start() first.")
        if self._collection.count() == 0:
            return []
        embeddings = await self._embed([text])
        kwargs: dict = {
            "query_embeddings": embeddings,
            "n_results": min(n, self._collection.count()),
        }
        if filters:
            kwargs["where"] = filters
        results = self._collection.query(**kwargs)
        out = []
        for i in range(len(results["ids"][0])):
            out.append(Result(
                id=results["ids"][0][i],
                text=results["documents"][0][i],
                metadata=results["metadatas"][0][i] or {},
                distance=results["distances"][0][i],
            ))
        return out

    async def delete(self, ids: list[str]) -> None:
        if self._collection is None:
            raise RuntimeError("RAG not started. Call start() first.")
        self._collection.delete(ids=ids)
