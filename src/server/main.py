import os
from contextlib import asynccontextmanager
from dataclasses import asdict

import chess
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from server.analysis import analyze
from server.engine import EngineAnalysis
from server.game import GameManager
from server.llm import ChessTeacher
from server.puzzles import PuzzleDB
from server.rag import ChessRAG


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return response


engine = EngineAnalysis(hash_mb=64)
teacher = ChessTeacher(ollama_url="https://ollama.st5ve.com")
rag = ChessRAG(ollama_url="https://ollama.st5ve.com", persist_dir="data/chromadb")
puzzle_db = PuzzleDB()
games = GameManager(engine, teacher=teacher, rag=rag)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await engine.start()
    await rag.start()
    await puzzle_db.start()
    yield
    await puzzle_db.close()
    await engine.stop()


app = FastAPI(title="Chess Teacher", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)


class AnalysisRequest(BaseModel):
    fen: str


class EvalRequest(BaseModel):
    fen: str
    depth: int = 20


class BestMovesRequest(BaseModel):
    fen: str
    n: int = 3
    depth: int = 20


class NewGameRequest(BaseModel):
    depth: int = 10
    elo_profile: str = "intermediate"


class MoveRequest(BaseModel):
    session_id: str
    move: str


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/analysis/position")
async def analysis_position(req: AnalysisRequest):
    try:
        board = chess.Board(req.fen)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid FEN: {req.fen}") from e
    report = analyze(board)
    return asdict(report)


@app.post("/api/engine/evaluate")
async def evaluate(req: EvalRequest):
    try:
        result = await engine.evaluate(req.fen, depth=req.depth)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
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
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return [
        {"uci": m.uci, "score_cp": m.score_cp, "score_mate": m.score_mate}
        for m in moves
    ]


@app.post("/api/game/new")
async def new_game(req: NewGameRequest | None = None):
    depth = req.depth if req else 10
    elo_profile = req.elo_profile if req else "intermediate"
    session_id, fen, status = games.new_game(depth=depth, elo_profile=elo_profile)
    return {"session_id": session_id, "fen": fen, "status": status}


@app.post("/api/game/move")
async def game_move(req: MoveRequest):
    try:
        result = await games.make_move(req.session_id, req.move)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return result


@app.get("/api/puzzle/random")
async def puzzle_random(
    theme: str | None = None,
    rating_min: int | None = None,
    rating_max: int | None = None,
    limit: int = 1,
):
    if not puzzle_db.available:
        raise HTTPException(status_code=503, detail="Puzzle database not available")
    themes = [t.strip() for t in theme.split(",") if t.strip()] if theme else None
    puzzles = await puzzle_db.get_random(
        themes=themes, rating_min=rating_min, rating_max=rating_max, limit=min(limit, 50),
    )
    return [
        {
            "id": p.id,
            "fen": p.fen,
            "moves": p.moves,
            "rating": p.rating,
            "themes": p.themes,
            "opening_tags": p.opening_tags,
        }
        for p in puzzles
    ]


@app.get("/api/puzzle/{puzzle_id}")
async def puzzle_by_id(puzzle_id: str):
    if not puzzle_db.available:
        raise HTTPException(status_code=503, detail="Puzzle database not available")
    puzzle = await puzzle_db.get_by_id(puzzle_id)
    if not puzzle:
        raise HTTPException(status_code=404, detail="Puzzle not found")
    return {
        "id": puzzle.id,
        "fen": puzzle.fen,
        "moves": puzzle.moves,
        "rating": puzzle.rating,
        "rating_deviation": puzzle.rating_deviation,
        "popularity": puzzle.popularity,
        "num_plays": puzzle.num_plays,
        "themes": puzzle.themes,
        "game_url": puzzle.game_url,
        "opening_tags": puzzle.opening_tags,
    }


# Mount static files last — catches all non-API routes
static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
