import os
import time
import pytest

# Settings requires these env vars at import time
os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434")
os.environ.setdefault("LLM_MODEL", "test-model")

from fastapi.testclient import TestClient
from server.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        # Wait for background init tasks to finish (stockfish, chromadb, puzzles)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            resp = c.get("/api/status")
            if resp.status_code == 200 and resp.json().get("ready"):
                break
            time.sleep(0.2)
        yield c


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_coep_coop_headers(client):
    """Static files need COEP/COOP headers for stockfish.wasm multi-threading."""
    response = client.get("/api/health")
    assert response.headers.get("Cross-Origin-Embedder-Policy") == "require-corp"
    assert response.headers.get("Cross-Origin-Opener-Policy") == "same-origin"


def test_evaluate_endpoint(client):
    response = client.post("/api/engine/evaluate", json={
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "depth": 10,
    })
    assert response.status_code == 200
    data = response.json()
    assert "score_cp" in data
    assert "best_move" in data
    assert "depth" in data


def test_evaluate_invalid_fen(client):
    response = client.post("/api/engine/evaluate", json={
        "fen": "not valid",
    })
    assert response.status_code == 400


def test_best_moves_endpoint(client):
    response = client.post("/api/engine/best-moves", json={
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "n": 3,
        "depth": 10,
    })
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_analysis_endpoint(client):
    response = client.post("/api/analysis/position", json={
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["fen"] == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    assert data["turn"] == "white"
    assert data["material"]["imbalance"] == 0
    assert data["material"]["white"]["pawns"] == 8
    assert data["development"]["white_developed"] == 0


def test_analysis_invalid_fen(client):
    response = client.post("/api/analysis/position", json={
        "fen": "not valid",
    })
    assert response.status_code == 400


def test_evaluate_illegal_fen(client):
    """Illegal position (opposite check) returns 400, not a crash."""
    response = client.post("/api/engine/evaluate", json={
        "fen": "8/8/8/8/8/8/6k1/r3K3 b - - 0 1",
    })
    assert response.status_code == 400
    assert "Illegal position" in response.json()["detail"]


def test_best_moves_illegal_fen(client):
    """Illegal position (opposite check) returns 400, not a crash."""
    response = client.post("/api/engine/best-moves", json={
        "fen": "8/8/8/8/8/8/6k1/r3K3 b - - 0 1",
    })
    assert response.status_code == 400
    assert "Illegal position" in response.json()["detail"]


def test_status_endpoint(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "ready" in data
    assert "tasks" in data
    assert "stockfish" in data["tasks"]
    assert "chromadb" in data["tasks"]
    assert "puzzles" in data["tasks"]
    for task in data["tasks"].values():
        assert "state" in task
        assert "detail" in task
