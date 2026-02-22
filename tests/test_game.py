from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from server.engine import Evaluation, MoveInfo
from server.game import GameManager
from server.llm import ChessTeacher
from server.main import app
from server.rag import Result


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


def test_move_response_has_coaching_field(client):
    """Move response includes coaching field (may be null for good moves)."""
    new = client.post("/api/game/new").json()
    sid = new["session_id"]

    resp = client.post("/api/game/move", json={
        "session_id": sid,
        "move": "e2e4",
    })
    assert resp.status_code == 200
    data = resp.json()
    # coaching field should be present (either null or a dict)
    assert "coaching" in data


def test_coaching_structure_when_present(client):
    """When coaching is returned, it has the expected structure."""
    new = client.post("/api/game/new").json()
    sid = new["session_id"]

    # Play a move
    resp = client.post("/api/game/move", json={
        "session_id": sid,
        "move": "e2e4",
    })
    data = resp.json()
    if data["coaching"] is not None:
        coaching = data["coaching"]
        assert "quality" in coaching
        assert "message" in coaching
        assert "arrows" in coaching
        assert "highlights" in coaching
        assert "severity" in coaching
        assert coaching["quality"] in ("brilliant", "good", "inaccuracy", "mistake", "blunder")
        assert isinstance(coaching["arrows"], list)
        assert isinstance(coaching["highlights"], list)


# ---------------------------------------------------------------------------
# Unit tests for GameManager LLM integration (mocked engine + teacher)
# ---------------------------------------------------------------------------


def _mock_engine():
    """Create a mock EngineAnalysis that returns plausible evaluations."""
    engine = AsyncMock()
    # eval_before: White +100, best move is d2d4
    engine.evaluate = AsyncMock(side_effect=[
        Evaluation(score_cp=100, score_mate=None, depth=12, best_move="d2d4", pv=["d2d4"]),
        # eval_after: White -200 (big drop — triggers coaching)
        Evaluation(score_cp=-200, score_mate=None, depth=12, best_move="d7d5", pv=["d7d5"]),
    ])
    # Opponent reply
    engine.best_moves = AsyncMock(return_value=[
        MoveInfo(uci="e7e5", score_cp=-10, score_mate=None),
    ])
    return engine


class TestGameManagerLLM:
    async def test_coaching_with_llm(self):
        """When teacher returns a message, it replaces the hardcoded one."""
        teacher = AsyncMock(spec=ChessTeacher)
        teacher.explain_move = AsyncMock(return_value="Great effort, but d4 controls the center better!")

        engine = _mock_engine()
        gm = GameManager(engine, teacher=teacher)
        sid, _, _ = gm.new_game()

        result = await gm.make_move(sid, "e2e4")
        assert result["coaching"] is not None
        assert result["coaching"]["message"] == "Great effort, but d4 controls the center better!"
        teacher.explain_move.assert_called_once()

    async def test_coaching_llm_fallback(self):
        """When teacher returns None, the hardcoded message is preserved."""
        teacher = AsyncMock(spec=ChessTeacher)
        teacher.explain_move = AsyncMock(return_value=None)

        engine = _mock_engine()
        gm = GameManager(engine, teacher=teacher)
        sid, _, _ = gm.new_game()

        result = await gm.make_move(sid, "e2e4")
        assert result["coaching"] is not None
        # Should contain the hardcoded message pattern (mentions pawn loss)
        assert "loses about" in result["coaching"]["message"]
        teacher.explain_move.assert_called_once()

    async def test_coaching_without_teacher(self):
        """When no teacher is provided, hardcoded messages are used."""
        engine = _mock_engine()
        gm = GameManager(engine, teacher=None)
        sid, _, _ = gm.new_game()

        result = await gm.make_move(sid, "e2e4")
        assert result["coaching"] is not None
        assert "loses about" in result["coaching"]["message"]

    async def test_coaching_with_rag_context(self):
        """When RAG returns knowledge, it reaches the LLM prompt."""
        teacher = AsyncMock(spec=ChessTeacher)
        teacher.explain_move = AsyncMock(return_value="Using fork knowledge!")

        rag = AsyncMock()
        rag.query = AsyncMock(return_value=[
            Result(id="1", text="A fork attacks two pieces.", metadata={"theme": "tactics"}, distance=0.1),
        ])

        engine = _mock_engine()
        gm = GameManager(engine, teacher=teacher, rag=rag)
        sid, _, _ = gm.new_game()

        result = await gm.make_move(sid, "e2e4")
        assert result["coaching"] is not None
        # Verify the teacher was called with RAG context in the MoveContext
        teacher.explain_move.assert_called_once()
        ctx = teacher.explain_move.call_args[0][0]
        assert "fork attacks two pieces" in ctx.rag_context

    async def test_coaching_without_rag(self):
        """When RAG is None, coaching still works normally."""
        teacher = AsyncMock(spec=ChessTeacher)
        teacher.explain_move = AsyncMock(return_value="No RAG but still coaching!")

        engine = _mock_engine()
        gm = GameManager(engine, teacher=teacher, rag=None)
        sid, _, _ = gm.new_game()

        result = await gm.make_move(sid, "e2e4")
        assert result["coaching"] is not None
        assert result["coaching"]["message"] == "No RAG but still coaching!"
        ctx = teacher.explain_move.call_args[0][0]
        assert ctx.rag_context == ""

    async def test_coaching_rag_failure_degrades_gracefully(self):
        """When RAG raises an exception, coaching continues without it."""
        teacher = AsyncMock(spec=ChessTeacher)
        teacher.explain_move = AsyncMock(return_value="Still works!")

        rag = AsyncMock()
        rag.query = AsyncMock(side_effect=Exception("RAG is down"))

        engine = _mock_engine()
        gm = GameManager(engine, teacher=teacher, rag=rag)
        sid, _, _ = gm.new_game()

        result = await gm.make_move(sid, "e2e4")
        assert result["coaching"] is not None
        assert result["coaching"]["message"] == "Still works!"
        # RAG context should be empty due to graceful degradation
        ctx = teacher.explain_move.call_args[0][0]
        assert ctx.rag_context == ""
