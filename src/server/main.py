import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import chess
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from server.analysis import analyze
from server.config import Settings
from server.engine import EngineAnalysis
from server.game import GameManager
from server.import_puzzles import (
    LICHESS_PUZZLE_URL,
    create_db,
    download_and_stream_csv,
    finalize_db,
    import_puzzles,
)
from server.knowledge import seed_knowledge_base
from server.llm import ChessTeacher
from server.puzzles import PuzzleDB
from server.rag import ChessRAG

logger = logging.getLogger(__name__)

settings = Settings()

# --- Initialization status tracking ---

_init_status: dict[str, dict] = {
    "stockfish": {"state": "pending", "detail": ""},
    "chromadb": {"state": "pending", "detail": ""},
    "puzzles": {"state": "pending", "detail": ""},
}


def _set_status(task: str, state: str, detail: str = "") -> None:
    _init_status[task] = {"state": state, "detail": detail}


def _all_done() -> bool:
    return all(t["state"] in ("done", "failed") for t in _init_status.values())


# --- Service instances ---

engine = EngineAnalysis(
    stockfish_path=settings.stockfish_path, hash_mb=settings.stockfish_hash_mb
)
teacher = ChessTeacher(
    base_url=settings.llm_base_url,
    model=settings.llm_model,
    api_key=settings.llm_api_key,
    timeout=settings.llm_timeout,
)
rag = ChessRAG(
    base_url=settings.effective_embed_base_url,
    model=settings.embed_model,
    api_key=settings.effective_embed_api_key,
    persist_dir=settings.chromadb_dir,
)
puzzle_db = PuzzleDB(db_path=settings.puzzle_db_path)
games = GameManager(engine, teacher=teacher, rag=rag)


# --- Background initialization tasks ---

async def _init_stockfish() -> None:
    _set_status("stockfish", "running", "Starting Stockfish engine...")
    try:
        await engine.start()
        _set_status("stockfish", "done", "Stockfish ready")
    except Exception as e:
        logger.error("Stockfish init failed: %s", e)
        _set_status("stockfish", "failed", str(e))


async def _init_chromadb() -> None:
    _set_status("chromadb", "running", "Starting ChromaDB...")
    try:
        await rag.start()
        # Seed knowledge base if empty
        if rag._collection is not None and rag._collection.count() == 0:
            _set_status("chromadb", "running", "Seeding knowledge base...")
            data_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "data", "knowledge_base.json"
            )
            if Path(data_path).exists():
                await seed_knowledge_base(rag, data_path)
        _set_status("chromadb", "done", "ChromaDB ready")
    except Exception as e:
        logger.error("ChromaDB init failed: %s", e)
        _set_status("chromadb", "failed", str(e))


async def _init_puzzles() -> None:
    db_path = settings.puzzle_db_path
    if Path(db_path).exists():
        _set_status("puzzles", "running", "Opening puzzle database...")
        await puzzle_db.start()
        _set_status("puzzles", "done", f"Puzzle database ready ({await _puzzle_count()} puzzles)")
        return

    if not settings.auto_init_puzzles:
        _set_status("puzzles", "done", "Puzzle database not found (auto-init disabled)")
        return

    _set_status("puzzles", "running", "Downloading puzzles from Lichess...")
    try:
        # Run blocking import in a thread
        def _do_import():
            conn = create_db(db_path)
            try:
                rows = download_and_stream_csv(LICHESS_PUZZLE_URL)

                def _on_progress(count):
                    _set_status("puzzles", "running", f"Importing puzzles ({count:,} rows)...")

                count = import_puzzles(conn, rows, verbose=False, on_progress=_on_progress)
                finalize_db(conn)
                return count
            finally:
                conn.close()

        count = await asyncio.to_thread(_do_import)
        await puzzle_db.start()
        _set_status("puzzles", "done", f"Imported {count:,} puzzles")
    except Exception as e:
        logger.error("Puzzle init failed: %s", e)
        _set_status("puzzles", "failed", str(e))


async def _puzzle_count() -> int:
    """Quick count for status messages."""
    try:
        return await puzzle_db.count()
    except Exception:
        return 0


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Launch all init tasks in background
    tasks = [
        asyncio.create_task(_init_stockfish()),
        asyncio.create_task(_init_chromadb()),
        asyncio.create_task(_init_puzzles()),
    ]
    yield
    # Cleanup
    for t in tasks:
        t.cancel()
    await puzzle_db.close()
    await engine.stop()


app = FastAPI(title="Chess Teacher", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)


# --- Request/Response models ---

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


# --- Endpoints ---

@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/status")
async def status():
    return {
        "ready": _all_done(),
        "tasks": _init_status,
    }


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
