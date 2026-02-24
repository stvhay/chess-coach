# Architecture

Chess Teacher teaches chess by combining three systems: Stockfish for
ground-truth position analysis, a local RAG store for positional patterns and
pedagogical content, and an LLM that orchestrates both and addresses the user as
a coaching persona. The LLM never evaluates positions itself — it translates
structured engine analysis and pattern matches into natural-language
explanations.

This document covers the full system architecture: runtime contexts, module
responsibilities, request lifecycle, integration points, and deployment. For the
analysis transformation chain see [ANALYSIS-PIPELINE.md](ANALYSIS-PIPELINE.md).
For technology choice rationale see [TRADE-OFFS.md](TRADE-OFFS.md).

## System Overview

The system runs in two contexts. The browser handles board interaction and
real-time evaluation display. The server handles game sessions, deep analysis,
coaching orchestration, and opponent move selection. A third machine (GPU box)
hosts the LLM and embedding model via Ollama.

```
┌─────────────────────────────────┐
│           Browser                   │
│  chessground (board UI)             │
│  chess.js (move validation)         │
│  stockfish.wasm (eval bar)          │
│  snabbdom (virtual DOM)             │
│  GameController (coordinator)       │
└──────────────┬──────────────────────┘
               │ JSON over HTTP
┌──────────────▼──────────────────────┐
│        FastAPI Server               │
│  Game sessions, analysis pipeline,  │
│  coaching orchestration             │
│         │              │            │
│    Stockfish       ChromaDB (RAG)   │
│    (UCI binary)    + Ollama embed   │
│         │                           │
│  Position analyzer                  │
│  (coded tactical/positional         │
│   concept detection)                │
│                                     │
│         └──── Ollama LLM ───────┐   │
│              (remote GPU)       │   │
└─────────────────────────────────┘   │
                                      │
              ┌───────────────────────┘
              │ HTTPS
┌─────────────▼───────────────────────┐
│  Ollama on 4070 Ti GPU              │
│  qwen2.5:14b (coaching LLM)        │
│  nomic-embed-text (RAG embeddings)  │
└─────────────────────────────────────┘
```

Two Stockfish instances run independently. The browser-side WASM build drives a
responsive eval bar that updates as the user navigates moves, running entirely in
a Web Worker with no server round-trip. The server-side UCI binary powers the
analysis pipeline: deep evaluation, MultiPV candidate generation, and mate threat
detection. The browser instance is lightweight (~7MB, lite single-threaded
build); the server instance runs at full strength.

The LLM (qwen2.5:14b) and embedding model (nomic-embed-text) run on a separate
4070 Ti GPU machine, accessed via Ollama's HTTP API. This separation keeps GPU
memory pressure off the application server and lets models be swapped or upgraded
independently.

## Server Architecture

The FastAPI application (`main.py`) bootstraps services during lifespan, applies
security headers middleware, and routes HTTP requests.

### Singletons Initialized at Startup

Five service objects, created during the FastAPI lifespan and shared across all
requests:

- **engine** (EngineAnalysis) — Stockfish UCI wrapper built on python-chess. An
  async lock serializes access because Stockfish is single-threaded. Includes
  crash recovery: if the process dies mid-analysis, the wrapper restarts it and
  retries.
- **teacher** (ChessTeacher) — Ollama HTTP client via httpx. Sends structured
  prompts assembled by the report serializer; returns natural-language
  explanations. Returns None on failure so the game proceeds without coaching.
- **rag** (ChessRAG) — ChromaDB embedded vector store paired with Ollama
  embedding via nomic-embed-text. Stores and retrieves positional patterns and
  pedagogical content by semantic similarity.
- **puzzle_db** (PuzzleDB) — SQLite database with FTS5 virtual tables holding
  5.7 million Lichess puzzles. WAL mode for concurrent reads. Degrades
  gracefully if the database file is missing.
- **games** (GameManager) — Owns the session dictionary; coordinates engine,
  teacher, and RAG for each coaching interaction.

### Module Map

Each server module has a single responsibility:

- **main.py** — FastAPI app: HTTP endpoints, COEP/COOP security headers
  middleware (required for SharedArrayBuffer in the browser), lifespan
  management, static file serving.
- **game.py** — GameManager: session management, move processing, coaching
  pipeline orchestration with a 20-second timeout to keep the game responsive.
- **engine.py** — EngineAnalysis: async Stockfish wrapper providing
  `evaluate()`, `analyze_lines()`, `best_moves()`, and
  `find_mate_threats()`. Retry-on-crash logic in `_analyse_with_retry()`.
- **coach.py** — Move assessment: classifies moves by centipawn loss into
  brilliant, good, inaccuracy, mistake, or blunder. Generates quick feedback
  text and board annotations (arrows, highlights).
- **analysis.py** — Pure-function position analysis (~955 lines): material
  counting, pawn structure, king safety, piece activity, tactical motifs,
  file/diagonal control, center control, development, and space. No Stockfish
  dependency; no side effects. See [ANALYSIS-PIPELINE.md](ANALYSIS-PIPELINE.md)
  and [DESIGN-THEORY.md](DESIGN-THEORY.md) for the analysis formalism.
- **game_tree.py** — GameTree and GameNode: two-pass tree construction (screen
  candidates wide at shallow depth, validate top candidates deep), teachability
  ranking, lazy per-node analysis.
- **descriptions.py** — Natural-language description layer:
  `describe_position()` renders active motifs into structured
  threats/opportunities/observations; `describe_changes()` diffs tactics
  between plies to surface what changed.
- **motifs.py** — Declarative motif registry: each MotifSpec entry maps a
  tactical or positional motif type to its identity extraction, rendering
  function, ray deduplication rules, and item caps. See [TACTICS.md](TACTICS.md)
  for motif details.
- **report.py** — Report serializer: DFS walk over the GameTree, calling
  description functions at each node, assembling a structured LLM prompt with
  PGN context, position descriptions, student move analysis, alternatives, and
  RAG context.
- **llm.py** — ChessTeacher: async Ollama client with two entry points —
  `explain_move()` for coaching explanations and `select_teaching_move()` for
  pedagogical opponent move selection.
- **rag.py** — ChessRAG: ChromaDB + Ollama embedding wrapper for semantic
  knowledge retrieval by position similarity.
- **knowledge.py** — RAG query construction: builds semantic searches from
  position analysis results, formats retrieved documents for LLM inclusion.
- **opponent.py** — Opponent move selection: detects game phase
  (opening/middlegame/endgame), filters Stockfish candidates by phase-specific
  centipawn thresholds, optionally delegates to the LLM for pedagogically
  interesting move choices.
- **elo_profiles.py** — Five difficulty profiles (beginner through competitive):
  each controls analysis depth, breadth, concept depth, and centipawn
  thresholds.
- **puzzles.py** — PuzzleDB: async SQLite wrapper for the Lichess puzzle
  database with FTS5 theme search and rating range filtering.
- **prompts/system.py** — System prompt sections for the coaching LLM:
  preamble, rules, severity guidance, perspective, and accuracy constraints.
- **prompts/formatting.py** — Opponent prompt builder: formats position context
  and candidate moves for LLM move selection.
- **lichess_tactics/** — Vendored Lichess-puzzler utilities: `is_hanging`,
  `is_trapped`, `can_be_taken_by_lower_piece`, with AST-hash drift detection
  to flag upstream changes.

### HTTP Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Health check |
| `/api/analysis/position` | POST | Pure-function position analysis (no engine) |
| `/api/engine/evaluate` | POST | Single-depth Stockfish evaluation |
| `/api/engine/best-moves` | POST | MultiPV candidate moves |
| `/api/game/new` | POST | Create game session (accepts elo_profile) |
| `/api/game/move` | POST | Apply player move, return coaching + opponent response |
| `/api/puzzle/random` | GET | Random puzzles with theme/rating filters |
| `/api/puzzle/{id}` | GET | Fetch puzzle by ID |

## Browser Architecture

The frontend is a vanilla TypeScript application with no framework. Snabbdom
serves only as chessground's internal virtual DOM dependency (~3KB). DOM
manipulation is direct.

### Module Map

- **main.ts** — App entry point: creates the DOM layout (header, board, coaching
  panel, eval bar, move list), initializes all subsystems, registers rendering
  callbacks, and handles keyboard navigation.
- **game.ts** — GameController: the central coordinator. Owns chess.js game
  state (authoritative source of truth), syncs chessground (visual board), manages
  ply-based history navigation with coaching cached per ply, handles promotion
  dialogs, and communicates with the server API.
- **board.ts** — Chessground wrapper: initializes the board with defaults (legal
  moves only, drag-and-drop, animation enabled) and returns the Api handle for
  programmatic control.
- **eval.ts** — BrowserEngine: wraps Stockfish WASM running in a Web Worker.
  Handles UCI protocol communication, accumulates MultiPV lines, and converts
  raw evaluations to visual bar position via a sigmoid function.
- **api.ts** — Type-safe HTTP client: `createGame()` and `sendMove()` with
  30-second timeout and typed request/response interfaces.

### Key Patterns

GameController coordinates all frontend activity. It owns chess.js state as the
single source of truth, syncs the chessground visual board to match, and handles
all API communication. main.ts registers rendering callbacks (update coaching
panel, update eval bar, update move list) with GameController, which fires them
after server responses arrive.

History navigation is ply-based. `jumpToPly()` reconstructs any position by
replaying moves from the root, then restores the cached coaching message for that
ply. Users review past explanations instantly, with no server round-trips.

### Build Pipeline

esbuild bundles TypeScript into `static/app.js` (ESM format). Chessground CSS
is concatenated from the npm package (base styles, brown board theme, cburnett
piece SVGs base64-encoded in CSS to avoid external requests). Stockfish WASM is
vendored in `static/vendor/stockfish/` (~7MB). FastAPI serves the entire
`static/` directory, with all non-API routes falling through to `index.html`.

## Data Flow: Player Move Lifecycle

A complete trace of `POST /api/game/move` from click to coaching response:

**1. Frontend validation.** GameController.handleMove() validates the move via
chess.js (legal move check), then calls `sendMove(sessionId, moveUci)`.

**2. API routing.** `main.py` routes the request to `GameManager.make_move()`.

**3. Pre-evaluation.** `engine.evaluate(board_before)` returns the position
score before the player's move — centipawn score, mate distance if applicable,
and the engine's best move.

**4. Apply move.** GameManager pushes the player's move to the board.

**5. Post-evaluation.** `engine.evaluate(board_after)` returns the score after
the move. The delta between pre- and post-evaluation determines move quality.

**6. Quick assessment.** `coach.assess_move()` classifies the move by centipawn
loss into a MoveQuality category (brilliant, good, inaccuracy, mistake, blunder)
and generates board annotations — arrows showing the best line, highlights on
key squares.

**7. Coaching pipeline** (20-second timeout). This is the deep analysis path
described in [ANALYSIS-PIPELINE.md](ANALYSIS-PIPELINE.md):

- `build_coaching_tree()` constructs a GameTree: first pass screens candidates
  wide with shallow MultiPV, second pass validates top candidates at deeper
  depth, then ranks nodes by teachability.
- `query_knowledge()` builds semantic searches from the position analysis and
  queries the RAG store for relevant pedagogical content.
- `serialize_report()` walks the game tree depth-first, calling
  `describe_position()` and `describe_changes()` at each node to produce
  structured natural-language context, then assembles the full LLM prompt.
- `explain_move()` sends the assembled prompt to the LLM via Ollama and
  receives the coaching explanation.

**8. Opponent response.** `select_opponent_move()` detects the current game
phase, filters Stockfish candidates by phase-specific centipawn thresholds
(tighter in openings, looser in tactical middlegames), and optionally delegates
to the LLM for a pedagogically motivated selection.

**9. Response.** The server returns JSON containing the new FEN, SAN notation for
both moves, game status flags, and coaching data (quality classification,
coaching message, arrows, highlights).

If the coaching pipeline times out, the game still proceeds — the response
includes the opponent's move but omits coaching. If the LLM is unreachable,
coaching degrades to engine analysis alone. The game never blocks on AI
availability.

## Integration Points

### Stockfish (UCI Protocol via python-chess)

Server-side EngineAnalysis wraps `chess.engine.popen_uci()`. An async lock
serializes all access because Stockfish is single-threaded — concurrent requests
queue rather than corrupt state. If Stockfish crashes mid-analysis,
`_analyse_with_retry()` restarts it and retries once before propagating the
error. Environment variables control configuration: `STOCKFISH_PATH` for the
binary location, `STOCKFISH_HASH_MB` for hash table size (default 64MB,
conservative for memory-constrained deployment).

Browser-side stockfish.wasm runs as a Web Worker using the lite single-threaded
build (~7MB). SharedArrayBuffer support requires COEP/COOP headers, applied by
the FastAPI middleware on every response.

### Ollama HTTP API

LLM generation uses `POST /api/chat` with OpenAI-compatible message format,
targeting qwen2.5:14b with a 15-second timeout per request. Embedding uses
`POST /api/embed` with nomic-embed-text (137M params, 768 dimensions) for RAG
semantic search. Both hit a remote endpoint (`https://ollama.st5ve.com/`) on the
4070 Ti GPU box, though the URL is configurable — any OpenAI-compatible API
works. All LLM and embedding calls return None on failure, so every dependent
feature degrades gracefully.

### ChromaDB (Embedded Vector Store)

ChromaDB runs in-process as a PersistentClient with SQLite + hnswlib backend
using cosine distance. The "chess_knowledge" collection stores enriched position
descriptions for semantic retrieval. A pydantic v1 BaseSettings import patch,
applied during the Docker build, maintains Python 3.14 compatibility.

### Puzzle Database (SQLite + FTS5)

The puzzle database holds 5.7 million Lichess puzzles with an FTS5 virtual table
for theme-based full-text search and rating range filtering. WAL mode enables
concurrent reads. If the database file is missing, puzzle endpoints return 503
rather than crashing — the rest of the application continues normally.
Random sampling deduplicates results to avoid returning the same puzzle twice
per session.

## Deployment Model

The application runs as a Docker container on a Xeon E5-1650 v4 (6 cores, 16GB
RAM, roughly 4GB free for the application). The base image is
`python:3.14-slim`. `uv sync --no-dev --frozen` installs dependencies from
`uv.lock` for reproducible builds. Stockfish comes from apt
(`/usr/games/stockfish`). The ChromaDB pydantic patch is applied during the
Docker build.

The frontend is pre-built (esbuild output) and served by FastAPI as static
files. Production requires no Node.js runtime.

Ollama runs on a separate machine (4070 Ti GPU) at a configurable URL. LAN
latency adds 1-5ms to LLM generation time. ChromaDB's persistent directory and
the puzzle SQLite database mount as Docker volumes for data persistence across
container restarts.

Health checks hit `GET /api/health` every 30 seconds.

**Development environment** uses a Nix devshell (`flake.nix`) providing Python
3.14, uv, the stockfish binary, and Node.js 22. Setup: `uv sync` for Python
dependencies, `npm install && npm run build` for the frontend, `uv run pytest`
for the 673+ test suite.

## Scalability Considerations

The current design targets a single user. Multi-user operation would require
changes in these areas:

**Game sessions.** GameManager holds sessions in an in-memory dictionary.
Multi-user requires persistent session storage (Redis or a database) with
session expiry to bound memory growth.

**Stockfish process pooling.** A single Stockfish process behind an async lock
means concurrent analysis requests queue sequentially. Multi-user requires a
process pool (one Stockfish instance per concurrent analysis) or a queue with
backpressure.

**RAG isolation.** The single "chess_knowledge" ChromaDB collection is shared.
Personalized knowledge (user-specific patterns, preferences) requires per-user
collections or metadata-based filtering within a shared collection.

**LLM throughput.** A single Ollama endpoint means concurrent coaching requests
queue at the GPU. Scaling requires multiple GPU workers, batched inference, or
migration to a cloud LLM API with higher throughput.

**Static analysis.** The `analysis.py` module is already pure functions —
stateless and thread-safe. This sole component scales horizontally without
modification.

## Local vs. Cloud LLM

The architecture uses local Ollama (self-hosted on 4070 Ti), but the interface
is deliberately minimal: an httpx POST to `/api/chat` with OpenAI-compatible
message format. Switching to a cloud provider means changing the `OLLAMA_URL`
environment variable to any OpenAI-compatible endpoint. ChessTeacher already
speaks the standard protocol.

Local advantages: positions stay on-premises (privacy), no per-token billing
(cost), LAN-controlled latency rather than internet round-trips, and no rate
limits. The trade-off is model size — the 4070 Ti's 12GB VRAM limits models to
roughly 14B parameters. Cloud APIs offer 70B+ models with potentially better
coaching quality at per-token cost.

The current model is qwen2.5:14b. Evaluation of qwen3:8b and qwen3:4b on the
coaching eval harness is planned to find the best quality-per-VRAM-GB ratio. See
[TRADE-OFFS.md](TRADE-OFFS.md) for broader discussion of technology choices.
