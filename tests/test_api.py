import pytest
from fastapi.testclient import TestClient
from server.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
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
