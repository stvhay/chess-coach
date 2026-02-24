# Trade-Offs

An honest accounting of Chess Teacher's significant technology and design
choices, what alternatives exist, and what limitations the current choices
impose. Every decision here closed some doors while opening others.

For system structure, see [ARCHITECTURE.md](ARCHITECTURE.md). For the analysis
pipeline design rationale, see ANALYSIS-PIPELINE.md (planned). For competitive
context on how these choices compare to existing tools, see LANDSCAPE.md
(planned).

---

## 1. Stockfish as Ground Truth

Chess Teacher uses Stockfish as its sole engine for position evaluation, best
move computation, and analysis pipeline input. The LLM never evaluates
positions itself. Every centipawn score, every principal variation, every move
classification originates from Stockfish.

**Why Stockfish:**

- Runs on CPU. The engine needs no GPU, which matters when the GPU serves
  Ollama for LLM inference.
- Deterministic at a given depth. The same position at depth 20 produces the
  same evaluation every time, making testing and debugging tractable.
- Stable output format. UCI protocol is mature, python-chess wraps it cleanly,
  and decades of community knowledge inform score interpretation.
- Fast. At depth 16-20 on a Xeon E5-1650 v4, single-position analysis
  completes in under a second.

**Alternatives considered:**

- **Leela Chess Zero (Lc0):** Neural network engine with strong positional
  intuition. The foundation design document notes that the `EngineAnalysis`
  interface could support Lc0 as a second backend, and that engine
  disagreements between Stockfish and Lc0 would be pedagogically interesting.
  Blocked by hardware: Lc0 needs GPU time, and the 4070 Ti runs Ollama. Adding
  Lc0 would require either a second GPU or careful time-sharing with LLM
  inference.
- **Maia Chess:** Trained on human games at specific Elo ranges, so it
  evaluates like a 1200 or 1600 player rather than a superhuman. Appealing for
  a teaching tool, but Maia's evaluations are unreliable as ground truth
  precisely because they model human error. You cannot ground coaching advice
  in an engine that deliberately makes mistakes.

**Limitations imposed:**

- Stockfish evaluations lack human intuition. A +0.3 advantage in a position
  with a beautiful outpost knight reveals nothing about why the position is
  good. The entire coded analysis layer in `analysis.py` bridges this gap.
- Stockfish occasionally prefers engine-optimal moves that teach poorly. The
  coaching quality iteration found this concretely: in an Italian Game
  position, Stockfish classified castling as an inaccuracy because it preferred
  d4 or c3. A valid engine opinion, but a human coach would never call O-O a
  mistake in the Italian.
- Without a GPU engine, no neural network evaluation is available, ruling out
  interesting pedagogical experiments with engine disagreement until the
  hardware situation changes.

---

## 2. Local LLM via Ollama

The coaching LLM runs locally on a 4070 Ti via Ollama, currently using
qwen2.5:14b. The LLM receives structured analysis from the position analyzer
and translates it into natural-language coaching. It never analyzes positions
itself.

**Why local:**

- Privacy. Game data and student interactions never leave the network.
- Cost. No per-token charges. Once the hardware exists, inference is free.
- Latency control. No dependency on external API availability or rate limits.
  The coaching pipeline targets sub-2-second responses at critical moments.
- Predictability. No surprise model deprecations, API changes, or provider
  outages.

**Alternatives considered:**

- **Cloud LLM APIs (OpenAI, Anthropic, etc.):** Better model quality,
  especially for nuanced explanations. Would allow GPT-4 or Claude-class
  responses instead of 14B-parameter models. Rejected because recurring API
  costs conflict with the self-hosting goal, and because teaching quality
  depends more on grounding (structured facts from the analysis pipeline)
  than on raw language model capability.
- **Larger local models:** 70B+ parameter models would improve response
  quality. Blocked by VRAM: a 4070 Ti has 16GB, which limits inference to
  around 14B parameters at reasonable quantization levels.

**Limitations imposed:**

- A 14B model is noticeably less articulate than GPT-4 or Claude. It
  occasionally produces awkward phrasing, misses nuance, and needs more
  explicit prompt engineering to avoid specific failure modes. The coaching
  quality iteration identified several: the model could not reliably infer
  piece ownership from algebraic notation case (N vs n), needed explicit side
  labels like "(student)" and "(opponent)" on each ply, and required a
  SEVERITY section in the system prompt to stop it from describing blunders
  as "a bit risky."
- Model exploration is constrained. Trying qwen3:8b or qwen3:4b (on the TODO
  list) is straightforward, but anything above ~14B remains out of reach
  without hardware changes.
- Network latency to the Ollama box adds round-trip time to every LLM call,
  since the GPU runs on a separate machine. The `ChessTeacher` class in
  `llm.py` uses a 15-second timeout and returns `None` on failure, triggering
  the graceful degradation path the UX requirements describe: the game
  continues without coaching commentary.

---

## 3. python-chess for Board Representation

python-chess is the standard Python library for chess programming. It provides
legal move generation, bitboard-backed piece lookup, FEN/PGN parsing,
Stockfish UCI integration, and pin-aware move validation.

**What it does well:**

- `board.legal_moves` generates only legal moves, correctly handling pins,
  checks, castling rights, and en passant. Several analysis functions build
  on this foundation.
- `board.attackers(color, square)` and `board.attacks(square)` provide
  fast bitboard-based attack computation.
- `board.is_pinned(color, square)` and `board.pin(color, square)` support
  pin-aware analysis. The overloaded-piece detector and square control
  functions use these to correct pseudo-legal attack maps.
- `chess.engine` handles UCI protocol management for Stockfish transparently.

**What it lacks:**

python-chess has no tactical pattern detection -- no `board.find_forks()`,
no `board.find_pins()`. It provides:

- `board.is_pinned()` -- whether a piece is absolutely pinned
- `board.attackers()` -- which pieces attack a square
- `board.attacks()` -- which squares a piece attacks (pseudo-legal)

Everything else -- fork detection, skewer detection, discovered attack
classification, hanging piece identification, overloaded piece analysis, mate
pattern recognition -- is custom code in `analysis.py` (roughly 1400 lines)
and the vendored Lichess tactical utilities. This constitutes the project's
single largest body of application-specific code.

---

## 4. Coded Analysis vs. LLM Analysis

The position analyzer (`analysis.py`) is pure Python: no Stockfish calls, no
LLM calls, no side effects. It takes a `chess.Board` and returns typed
dataclass instances describing material, pawn structure, king safety, piece
activity, tactical motifs, files and diagonals, center control, development,
and space.

**Why coded, not LLM-generated:**

- LLMs hallucinate chess analysis. They confidently describe pins that do not
  exist, miss forks that do, and invent piece placements. This is not a
  solvable prompting problem -- it is a fundamental limitation of language
  models operating on positional data. The project's core architectural
  principle: the LLM explains; it never analyzes.
- Coded functions are deterministic and testable. The test suite includes
  673 tests covering tactical detection, pawn analysis, ray motifs, game tree
  construction, and coaching report generation. An LLM-based analyzer would
  require statistical evaluation rather than deterministic assertions.
- Structured output. The analysis produces typed dataclass instances that the
  motif registry, tactic diffing, and report serialization consume
  programmatically. LLM output is text that needs parsing.

**How the boundary works:**

1. `analysis.py` computes structured facts about a position.
2. `descriptions.py` translates those facts into labeled natural language
   ("White's rook on e1 controls the open e-file").
3. `report.py` walks the game tree and assembles a structured prompt
   containing only pre-computed facts.
4. `llm.py` sends that prompt to Ollama and receives a coaching message.

The LLM sees statements like "New tactic: White Bishop on b5 pins Black
Knight on c6 to Black King on e8 (absolute pin)." It never sees a FEN string
and never determines whether a pin exists.

**Limitations imposed:**

- The coded analysis is only as good as its implementations. Each tactical
  detector was written and tested against specific positions, but thin
  coverage (one positive case per tactic type in early testing) let bugs
  survive until the coaching evaluation harness caught them.
- New tactical concepts require new code. An LLM could potentially recognize
  novel patterns that no detector handles. The coded approach requires writing
  a detection function, adding it to the motif registry, wiring it through
  descriptions and report serialization, and adding tests.
- The analysis runs per-position, not per-move-sequence. Multi-move tactical
  themes like attraction (luring a piece to a vulnerable square over several
  moves) are fundamentally multi-ply concepts. The Lichess puzzler's
  `attraction` function remains on the watchlist because it operates on game
  tree nodes, not static boards.

---

## 5. chessground + snabbdom vs. React/Vue

The frontend uses chessground (the Lichess board library), snabbdom (a ~3KB
virtual DOM library), and plain TypeScript. The `package.json` reveals the
choice by what it omits: no React, no Vue, no Angular, no Next.js, no state
management library, no CSS-in-JS.

**Why this stack:**

- chessground is battle-tested. It powers Lichess, which serves millions of
  games per day. It handles piece dragging, move animation, board orientation,
  arrows, square highlighting, premoves, and accessibility. Building a chess
  board UI from scratch would take months and produce an inferior result.
- snabbdom is minimal. At ~3KB, it provides virtual DOM diffing for the
  coaching panel and UI shell without a framework runtime. The total frontend
  bundle stays small and fast.
- esbuild bundles TypeScript with near-instant build times. No webpack
  configuration, no babel plugins, no build-time complexity.

**Alternatives considered:**

- **React:** Larger ecosystem, better component abstractions, more developer
  familiarity. Rejected because the UI lacks the complexity to justify a
  framework runtime. The application has one primary view (board + coaching
  panel), not a multi-route SPA.
- **Vue:** Similar reasoning. The coaching panel is the only interactive
  non-board element, and snabbdom handles it adequately.
- **Svelte:** Closer to the "minimal runtime" philosophy. A reasonable
  alternative, passed over primarily because chessground integration patterns
  are better documented for vanilla JS.

**Limitations imposed:**

- Sparse ecosystem support. No component library, no ready-made UI patterns,
  no community recipes for common interactions. The hamburger menu with Elo
  dropdown, the eval bar, and the coaching panel all require manual DOM
  management via snabbdom.
- Steeper contributor learning curve. Most frontend developers know React;
  fewer know snabbdom.
- No server-side rendering. The application is a static JS bundle served by
  FastAPI. This suits the current use case (a tool, not a content site) but
  means no SEO, no progressive enhancement, and no server-rendered initial
  state.

---

## 6. ChromaDB for RAG

ChromaDB is an embedded vector store for the retrieval-augmented generation
pipeline. It stores position descriptions as natural-language chunks with
vector embeddings from `nomic-embed-text` via Ollama.

**Why ChromaDB:**

- Embedded: runs in-process with the Python application, requiring no separate
  database server.
- Simple API: ingest chunks, query by similarity, filter by metadata. The
  `ChessRAG` interface wraps it cleanly.
- Adequate scale: the knowledge base measures in thousands of chunks, not
  millions. ChromaDB's in-process SQLite + hnswlib index handles this
  comfortably within the ~4GB available RAM on the deployment target.

**Alternatives considered:**

- **pgvector (PostgreSQL):** More robust, better query capabilities, standard
  SQL for metadata filtering. Rejected because it requires a separate
  PostgreSQL server, adding operational complexity on a memory-constrained
  deployment target.
- **Qdrant / Weaviate / Pinecone:** Feature-rich vector databases. Rejected
  because they either require cloud hosting (Pinecone) or run heavier than
  the dataset size warrants (Qdrant/Weaviate as separate services).
- **FAISS:** Facebook's similarity search library. Lower-level than ChromaDB;
  metadata storage would need separate construction. ChromaDB bundles
  metadata, persistence, and vector search into one package.

**Limitations imposed:**

- Python 3.14 compatibility issue. ChromaDB depends on pydantic v1's
  `BaseSettings`, removed in newer pydantic versions. This requires a patch
  in the virtual environment. The issue awaits upstream resolution.
- Scale ceiling. ChromaDB handles thousands of vectors well but falters at
  millions. If the knowledge base grows significantly (e.g., indexing large
  opening databases at per-position granularity), it will need replacing. The
  `ChessRAG` interface anticipates exactly this: the storage backend can
  change without affecting the rest of the application.
- No graph queries. The planned graph-structured RAG (position DAGs with
  color-normalized hashing, transposition detection, ancestor/descendant
  walks) requires graph traversal beyond ChromaDB's flat
  vector-plus-metadata model. Graph edges will be stored as metadata fields,
  but traversal will remain application code, not database queries.

---

## 7. Vendored Lichess Code

Tactical detection functions from `lichess-puzzler` (the engine behind
Lichess's puzzle generation) are vendored into `src/server/lichess_tactics/`
with AST-hash-based drift detection.

**What is vendored:**

- `is_hanging`: X-ray-aware hanging piece detection
- `is_trapped`: Piece with no safe escape squares
- `is_in_bad_spot`, `can_be_taken_by_lower_piece`: Positional vulnerability
- Mate pattern detectors: back rank, smothered, arabian, hook, anastasia,
  dovetail, boden, double bishop, scholars, fools, epaulette, lolli
- `exposed_king`: King safety assessment from attacker's perspective

**Why vendor rather than depend:**

- The upstream API is unstable. `lichess-puzzler` is an internal tool, not a
  published library. Its function signatures and behavior change without
  versioning guarantees.
- The project's needs are specific. Some functions are used directly (e.g.,
  `is_hanging`), while others are adapted. The upstream `fork` function
  operates on puzzle game tree nodes (iterating `ChildNode` moves), not
  static boards, so it was reimplemented in `analysis.py`.
- Selective vendoring keeps scope tight. Only 10 functions from `_util.py` and
  11 from `_cook.py` are vendored. Another 12 sit on a watchlist (status
  "watching" in `upstream.json`) for potential future adoption.

**How drift detection works:**

`upstream.json` records a per-function AST hash for each vendored and watched
function, pinned to upstream commit d021969. The drift test suite re-parses
the upstream source, computes AST hashes, and hard-fails if a vendored
function's hash changes without acknowledgment. This catches upstream changes
that might invalidate the vendored copy.

**Limitations imposed:**

- Maintenance burden. Every upstream change to a vendored function requires
  manual review: is the change relevant? Does it fix a bug? Does it break
  assumptions? The watchlist of 12 unvendored functions compounds this cost.
- License coupling. `lichess-puzzler` is AGPL-3.0, which propagates to the
  vendored code. The package header notes this.
- Some upstream patterns are fundamentally multi-move (attraction, deflection,
  interference). These cannot adapt to static board analysis without
  rethinking the detection approach, which is why they remain on the watchlist
  rather than vendored.

---

## 8. Two Stockfish Instances

The application runs Stockfish in two places: as a WASM binary in the browser
(via web worker) and as a native binary on the server (via python-chess UCI).

**Why two rather than one:**

- Different latency requirements. The browser engine powers the eval bar,
  which must update responsively as the user drags pieces. It runs
  continuously at moderate depth. The server engine powers the analysis
  pipeline, running at higher depth on specific positions when the coaching
  system needs it.
- Different depth needs. Browser-side: depth 12-16, fast and continuous.
  Server-side: depth 16-20+, thorough and batched.
- WASM constraints. The browser Stockfish is a single-threaded lite build
  (~7MB) that cannot match native binary performance. Sharing it for analysis
  pipeline work would create unacceptable latency.
- Failure isolation. If the server goes down, the browser engine can generate
  opponent moves as a fallback. If the browser engine fails (WASM
  incompatibility, SharedArrayBuffer unavailable), the eval bar disappears
  but the game continues with server-side analysis. The UX requirements
  specify this degradation chain explicitly.

**Cost:**

- Memory. Two Stockfish instances consume more RAM than one. On the server
  (Xeon E5-1650 v4, ~4GB free), conservative hash table settings manage this.
  The browser instance uses whatever memory the browser allocates.
- Complexity. COEP and COOP headers on all responses support
  SharedArrayBuffer in the browser, which stockfish.wasm needs for threading.
  This adds a middleware concern in FastAPI and a deployment constraint.

---

## 9. Pseudo-Legal Tolerance

`board.attacks()` in python-chess computes pseudo-legal attacks: it shows
where a piece could move while ignoring pins on that piece. A bishop pinned to
its king still "attacks" squares along its diagonals, even though it cannot
legally move there.

**The design choice:**

The analysis uses pseudo-legal attack maps for aggregate measures (center
control, space calculation, piece activity/mobility) but restricts to legal
moves for critical correctness queries (overloaded-piece detection, sole
defender identification, capturable defender analysis).

DESIGN-THEORY.md Section 5 documents this as the "pin-blindness" problem. The
code addresses it two ways:

1. `_can_defend()` in `analysis.py` checks `board.is_pinned()` and
   `board.pin()` to verify that a claimed defender can actually recapture on
   the target square. `_find_overloaded_pieces()` and
   `_find_capturable_defenders()` use this.
2. `_analyze_square_control()` has a `pin_aware` parameter (default `True`)
   that excludes pinned pieces from the attacker count when they cannot reach
   the target square along their pin ray.

**Why tolerate pseudo-legal for aggregate measures:**

- Computing fully legal attack maps for every piece on every square is
  expensive, requiring a legality test for each (piece, target) pair by
  simulating the move and checking for self-check.
- For aggregate measures (how many squares does this knight "control"?), the
  pseudo-legal approximation suffices. A pinned knight on c3 still exerts
  latent pressure on the squares it attacks -- the pin could break, the
  pinner could fall.
- The error is bounded. At most one or two pieces per side are pinned in a
  typical position, so aggregate scores drift by only a small amount.

**Limitations imposed:**

- Center control and space scores can overcount when pieces are pinned. A
  pinned bishop "controlling" d5 inflates White's center control score even
  though the bishop cannot legally move there.
- Activity assessments (restricted/normal/active) can misclassify a pinned
  piece. A pinned rook on an open file appears active by mobility count but
  is functionally restricted.
- This is a known, accepted approximation. Eliminating it everywhere would add
  significant complexity for minimal coaching quality improvement.

---

## 10. Dark Theme Only

The application uses a dark color scheme exclusively. No light mode is
planned.

**Rationale:**

- Chess boards look better on dark backgrounds. The wooden board aesthetic and
  piece contrast work naturally with dark surroundings.
- Matches Lichess convention. The primary user base (chess players studying
  online) expects dark interfaces.
- One theme means one set of CSS variables, one set of contrast ratios to
  validate, and no theme-switching state management.
- The accent color (green) signals pedagogy: green conventionally means "good
  move" in chess UIs.

**Limitations imposed:**

- Accessibility gap. Some users with low-vision conditions work better against
  light backgrounds. No accommodation exists.
- Preference. Some users prefer light themes and cannot be served.
- Environmental context. A dark theme in a brightly lit room causes eye strain.
  The application offers no adaptation.

This is a deliberate scope cut. Supporting two themes costs more than CSS -- it
means testing every UI state in both modes, maintaining contrast ratios in
both, and handling the inevitable edge cases where one theme breaks.

---

## 11. Hardware Constraints

The deployment target is a dedicated server with an Intel Xeon E5-1650 v4
(6 cores, 12 threads), 16GB RAM (~4GB free after OS and other services), and
Docker. LLM inference runs on a separate 4070 Ti GPU box accessible via
network.

**What this forces:**

- Conservative Stockfish hash tables. The `EngineAnalysis` class in `engine.py`
  defaults to 64MB hash, well below Stockfish's typical recommended settings,
  because default sizes consume too much RAM.
- Limited concurrent analysis. Server-side Stockfish holds an `asyncio.Lock`
  and processes one analysis request at a time. Multiple simultaneous users
  queue behind each other. Scaling to concurrent sessions would require
  multiple engine instances (consuming more RAM) or request batching.
- ChromaDB's in-process SQLite and hnswlib index must fit in available memory.
  Thousands of chunks are fine, but this sets a ceiling on knowledge base
  growth.
- Network latency to the Ollama box. LLM calls cross the network, adding
  round-trip time that a colocated GPU would eliminate. The `ChessTeacher`
  class handles this with timeout-based fallback: if the LLM fails to respond
  within 15 seconds, coaching is skipped and the game continues.

**What it enables:**

- Straightforward Docker deployment. The application itself (FastAPI +
  python-chess + ChromaDB) is lightweight. Stockfish is a single binary.
  No GPU driver management on the application server.
- The Xeon's 6 cores handle the web server, Stockfish analysis, and ChromaDB
  queries concurrently, even under moderate load.
- Splitting LLM inference to a separate GPU box keeps the application server
  free from model inference contention. Each machine does what it does best.

**Future pressure points:**

- Multiple simultaneous users will hit the single-engine lock. The path
  forward: a pool of Stockfish instances or an analysis queue with priority
  scheduling.
- Growing the RAG knowledge base (e.g., indexing the full Lichess puzzle
  database of 5.7M puzzles at per-position granularity) will eventually
  exceed ChromaDB's comfortable working set in 4GB of available RAM.
- Moving toward local LLM inference (eliminating the network hop) would
  require adding a GPU to the application server or upgrading to a machine
  with more RAM and a GPU.
