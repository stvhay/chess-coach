"""Tests for WebSocketEngine — EngineProtocol over WebSocket."""
import asyncio
import json

import pytest

from server.engine import EngineProtocol, Evaluation, LineInfo, MoveInfo
from server.ws_engine import WebSocketEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeWebSocket:
    """Simulates a FastAPI WebSocket for testing."""

    def __init__(self):
        self._sent: list[str] = []
        self._receive_queue: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def send_text(self, data: str) -> None:
        self._sent.append(data)

    async def receive_text(self) -> str:
        return await self._receive_queue.get()

    def enqueue_response(self, data: dict) -> None:
        """Queue a JSON response for the engine to receive."""
        self._receive_queue.put_nowait(json.dumps(data))

    @property
    def sent_messages(self) -> list[dict]:
        return [json.loads(s) for s in self._sent]


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

def test_ws_engine_implements_protocol():
    assert issubclass(WebSocketEngine, EngineProtocol)


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

@pytest.fixture
def ws_engine():
    return WebSocketEngine()


@pytest.fixture
def fake_ws():
    return FakeWebSocket()


async def test_evaluate_sends_request_and_returns_result(ws_engine, fake_ws):
    ws_engine.attach(fake_ws)

    # Schedule response after engine sends request
    async def respond():
        # Wait for request to be sent
        while not fake_ws._sent:
            await asyncio.sleep(0.01)
        req = json.loads(fake_ws._sent[0])
        fake_ws.enqueue_response({
            "id": req["id"],
            "result": {
                "score_cp": 35,
                "score_mate": None,
                "depth": 20,
                "best_move": "e2e4",
                "pv": ["e2e4", "e7e5", "g1f3"],
            },
        })

    asyncio.create_task(respond())
    result = await ws_engine.evaluate("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", depth=20)

    assert isinstance(result, Evaluation)
    assert result.score_cp == 35
    assert result.best_move == "e2e4"
    assert result.pv == ["e2e4", "e7e5", "g1f3"]

    # Verify request format
    req = fake_ws.sent_messages[0]
    assert req["method"] == "evaluate"
    assert req["params"]["fen"] == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    assert req["params"]["depth"] == 20


# ---------------------------------------------------------------------------
# analyze_lines
# ---------------------------------------------------------------------------

async def test_analyze_lines(ws_engine, fake_ws):
    ws_engine.attach(fake_ws)

    async def respond():
        while not fake_ws._sent:
            await asyncio.sleep(0.01)
        req = json.loads(fake_ws._sent[0])
        fake_ws.enqueue_response({
            "id": req["id"],
            "result": [
                {"uci": "e2e4", "san": "e4", "score_cp": 30, "score_mate": None, "pv": ["e2e4", "e7e5"], "depth": 16},
                {"uci": "d2d4", "san": "d4", "score_cp": 25, "score_mate": None, "pv": ["d2d4", "d7d5"], "depth": 16},
            ],
        })

    asyncio.create_task(respond())
    result = await ws_engine.analyze_lines(
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", n=2, depth=16,
    )

    assert len(result) == 2
    assert isinstance(result[0], LineInfo)
    assert result[0].uci == "e2e4"
    assert result[0].san == "e4"


# ---------------------------------------------------------------------------
# best_moves
# ---------------------------------------------------------------------------

async def test_best_moves(ws_engine, fake_ws):
    ws_engine.attach(fake_ws)

    async def respond():
        while not fake_ws._sent:
            await asyncio.sleep(0.01)
        req = json.loads(fake_ws._sent[0])
        fake_ws.enqueue_response({
            "id": req["id"],
            "result": [
                {"uci": "e2e4", "score_cp": 30, "score_mate": None},
                {"uci": "d2d4", "score_cp": 25, "score_mate": None},
            ],
        })

    asyncio.create_task(respond())
    result = await ws_engine.best_moves(
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", n=2, depth=20,
    )

    assert len(result) == 2
    assert isinstance(result[0], MoveInfo)
    assert result[0].uci == "e2e4"


# ---------------------------------------------------------------------------
# find_mate_threats
# ---------------------------------------------------------------------------

async def test_find_mate_threats(ws_engine, fake_ws):
    ws_engine.attach(fake_ws)

    async def respond():
        while not fake_ws._sent:
            await asyncio.sleep(0.01)
        req = json.loads(fake_ws._sent[0])
        fake_ws.enqueue_response({
            "id": req["id"],
            "result": [
                {"threatening_color": "white", "mating_square": "h7", "depth": 2, "mating_move": "Qh7#"},
            ],
        })

    asyncio.create_task(respond())
    result = await ws_engine.find_mate_threats(
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    )

    assert len(result) == 1
    assert result[0]["mating_move"] == "Qh7#"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

async def test_error_response_raises(ws_engine, fake_ws):
    ws_engine.attach(fake_ws)

    async def respond():
        while not fake_ws._sent:
            await asyncio.sleep(0.01)
        req = json.loads(fake_ws._sent[0])
        fake_ws.enqueue_response({"id": req["id"], "error": "Engine not ready"})

    asyncio.create_task(respond())
    with pytest.raises(RuntimeError, match="Engine not ready"):
        await ws_engine.evaluate("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


async def test_no_websocket_raises(ws_engine):
    with pytest.raises(RuntimeError, match="No browser engine connected"):
        await ws_engine.evaluate("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


async def test_timeout_raises(ws_engine, fake_ws):
    ws_engine.attach(fake_ws)
    ws_engine._timeout = 0.1  # Override for fast test

    with pytest.raises(RuntimeError, match="timed out"):
        await ws_engine.evaluate("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


# ---------------------------------------------------------------------------
# attach replaces previous connection
# ---------------------------------------------------------------------------

async def test_attach_replaces_previous(ws_engine, fake_ws):
    ws_engine.attach(fake_ws)

    fake_ws2 = FakeWebSocket()
    ws_engine.attach(fake_ws2)

    # New connection is active
    async def respond():
        while not fake_ws2._sent:
            await asyncio.sleep(0.01)
        req = json.loads(fake_ws2._sent[0])
        fake_ws2.enqueue_response({
            "id": req["id"],
            "result": {"score_cp": 0, "score_mate": None, "depth": 20, "best_move": "e2e4", "pv": ["e2e4"]},
        })

    asyncio.create_task(respond())
    result = await ws_engine.evaluate("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert isinstance(result, Evaluation)
