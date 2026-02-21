import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from server.engine import EngineAnalysis
from server.game import GameManager


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return response


engine = EngineAnalysis(hash_mb=64)
games = GameManager(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await engine.start()
    yield
    await engine.stop()


app = FastAPI(title="Chess Teacher", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)


class EvalRequest(BaseModel):
    fen: str
    depth: int = 20


class BestMovesRequest(BaseModel):
    fen: str
    n: int = 3
    depth: int = 20


class NewGameRequest(BaseModel):
    depth: int = 10


class MoveRequest(BaseModel):
    session_id: str
    move: str


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/engine/evaluate")
async def evaluate(req: EvalRequest):
    try:
        result = await engine.evaluate(req.fen, depth=req.depth)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "score_cp": result.score_cp,
        "score_mate": result.score_mate,
        "depth": result.depth,
        "best_move": result.best_move,
        "pv": result.pv,
    }


@app.post("/api/engine/best-moves")
async def best_moves(req: BestMovesRequest):
    try:
        moves = await engine.best_moves(req.fen, n=req.n, depth=req.depth)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [
        {"uci": m.uci, "score_cp": m.score_cp, "score_mate": m.score_mate}
        for m in moves
    ]


@app.post("/api/game/new")
async def new_game(req: NewGameRequest | None = None):
    depth = req.depth if req else 10
    session_id, fen, status = games.new_game(depth=depth)
    return {"session_id": session_id, "fen": fen, "status": status}


@app.post("/api/game/move")
async def game_move(req: MoveRequest):
    try:
        result = await games.make_move(req.session_id, req.move)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


# Mount static files last — catches all non-API routes
static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
