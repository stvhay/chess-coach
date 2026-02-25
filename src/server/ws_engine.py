"""WebSocket-based engine backend.

Implements EngineProtocol by dispatching analysis requests to a browser
running Stockfish WASM. The browser connects via WebSocket and acts as
a remote UCI engine.
"""

import asyncio
import itertools
import json
import logging

from server.engine import EngineProtocol, Evaluation, LineInfo, MoveInfo

logger = logging.getLogger(__name__)


class WebSocketEngine(EngineProtocol):
    """Engine backend that dispatches to browser WASM Stockfish over WebSocket."""

    def __init__(self, timeout: float = 30.0):
        self._ws = None
        self._lock = asyncio.Lock()
        self._timeout = timeout
        self._pending: dict[str, asyncio.Future] = {}
        self._counter = itertools.count(1)
        self._reader_task: asyncio.Task | None = None

    def attach(self, ws) -> None:
        """Attach a WebSocket connection. Replaces any previous connection."""
        # Cancel previous reader
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        # Fail any pending requests from old connection
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("Browser engine reconnected"))
        self._pending.clear()
        self._ws = ws
        self._reader_task = asyncio.create_task(self._read_loop())

    def detach(self) -> None:
        """Detach the current WebSocket connection."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("Browser engine disconnected"))
        self._pending.clear()
        self._ws = None

    async def _read_loop(self) -> None:
        """Background task that reads WebSocket responses and resolves futures."""
        try:
            while self._ws:
                raw = await self._ws.receive_text()
                msg = json.loads(raw)
                req_id = msg.get("id")
                if req_id and req_id in self._pending:
                    fut = self._pending.pop(req_id)
                    if not fut.done():
                        fut.set_result(msg)
        except Exception:
            # Connection closed or cancelled — fail pending requests
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("Browser engine disconnected"))
            self._pending.clear()

    async def _request(self, method: str, params: dict) -> dict:
        """Send a request and wait for the response."""
        if self._ws is None:
            raise RuntimeError("No browser engine connected")

        req_id = f"req-{next(self._counter)}"
        payload = json.dumps({"id": req_id, "method": method, "params": params})

        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut

        await self._ws.send_text(payload)

        try:
            msg = await asyncio.wait_for(fut, timeout=self._timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise RuntimeError(f"Browser engine timed out on {method}")

        if "error" in msg:
            raise RuntimeError(msg["error"])

        return msg["result"]

    async def evaluate(self, fen: str, depth: int = 20) -> Evaluation:
        async with self._lock:
            result = await self._request("evaluate", {"fen": fen, "depth": depth})
        return Evaluation(
            score_cp=result["score_cp"],
            score_mate=result["score_mate"],
            depth=result["depth"],
            best_move=result["best_move"],
            pv=result["pv"],
        )

    async def analyze_lines(self, fen: str, n: int = 5, depth: int = 16) -> list[LineInfo]:
        async with self._lock:
            result = await self._request("analyze_lines", {"fen": fen, "n": n, "depth": depth})
        return [
            LineInfo(
                uci=line["uci"],
                san=line["san"],
                score_cp=line["score_cp"],
                score_mate=line["score_mate"],
                pv=line["pv"],
                depth=line["depth"],
            )
            for line in result
        ]

    async def best_moves(self, fen: str, n: int = 3, depth: int = 20) -> list[MoveInfo]:
        async with self._lock:
            result = await self._request("best_moves", {"fen": fen, "n": n, "depth": depth})
        return [
            MoveInfo(
                uci=move["uci"],
                score_cp=move["score_cp"],
                score_mate=move["score_mate"],
            )
            for move in result
        ]

    async def find_mate_threats(self, fen: str, max_depth: int = 3, eval_depth: int = 10) -> list[dict]:
        async with self._lock:
            result = await self._request(
                "find_mate_threats", {"fen": fen, "max_depth": max_depth, "eval_depth": eval_depth},
            )
        return result
