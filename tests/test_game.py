import pytest
from fastapi.testclient import TestClient
from server.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_new_game(client):
    """POST /api/game/new creates a session with starting position."""
    response = client.post("/api/game/new")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["fen"] == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    assert data["status"] == "playing"


def test_make_move(client):
    """POST /api/game/move applies player move and returns opponent response."""
    new = client.post("/api/game/new").json()
    sid = new["session_id"]

    response = client.post("/api/game/move", json={
        "session_id": sid,
        "move": "e2e4",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["player_move_san"] == "e4"
    assert "opponent_move_uci" in data
    assert "opponent_move_san" in data
    assert "fen" in data
    assert data["status"] in ("playing", "checkmate", "stalemate", "draw")
    # After opponent moves, it should be white's turn again
    assert " w " in data["fen"]


def test_invalid_move(client):
    """Invalid UCI move returns 400."""
    new = client.post("/api/game/new").json()
    sid = new["session_id"]

    response = client.post("/api/game/move", json={
        "session_id": sid,
        "move": "e2e5",
    })
    assert response.status_code == 400


def test_invalid_session(client):
    """Non-existent session returns 404."""
    response = client.post("/api/game/move", json={
        "session_id": "00000000-0000-0000-0000-000000000000",
        "move": "e2e4",
    })
    assert response.status_code == 404


def test_game_over_detection(client):
    """After a normal move, status is 'playing'."""
    new = client.post("/api/game/new").json()
    sid = new["session_id"]

    resp = client.post("/api/game/move", json={
        "session_id": sid,
        "move": "e2e4",
    })
    assert resp.json()["status"] == "playing"


def test_multiple_moves(client):
    """Multiple moves in sequence work correctly."""
    new = client.post("/api/game/new").json()
    sid = new["session_id"]

    r1 = client.post("/api/game/move", json={
        "session_id": sid,
        "move": "e2e4",
    })
    assert r1.status_code == 200
    assert r1.json()["status"] == "playing"

    r2 = client.post("/api/game/move", json={
        "session_id": sid,
        "move": "d2d4",
    })
    assert r2.status_code == 200
    assert r2.json()["status"] == "playing"


def test_new_game_with_depth(client):
    """POST /api/game/new accepts optional depth parameter."""
    response = client.post("/api/game/new", json={"depth": 5})
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
