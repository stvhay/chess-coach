# Design Documentation Plan

This document provides independent agents with the context needed to write each
design document. Each section is self-contained: an agent should be able to read
its brief, the listed source files, and produce the document without knowledge of
the other sections being written in parallel.

All documents live in `guide/`. The project is a chess teaching web application
that combines Stockfish (position analysis), a local RAG knowledge base, and a
local LLM to coach beginner-to-intermediate chess players during live games.

---

## Document Inventory

| Document | Status | Description |
|----------|--------|-------------|
| DESIGN.md | **Written** | Hub document — purpose, motivation, vision, overview, links |
| PEDAGOGY.md | **Written** | Teaching philosophy and coaching model |
| UX.md | **Written** | User interaction flows, user stories, delegation model |
| UI.md | **Written** | Interface layout, visual design, component structure |
| ARCHITECTURE.md | **Written** | Software structure, modules, data flow, deployment |
| ANALYSIS-PIPELINE.md | **Written** | The transformation chain from board position to coaching prompt |
| DESIGN-THEORY.md | **Exists** | Position analysis formalism — maps MATH.md concepts to code |
| TRADE-OFFS.md | **Written** | Technology choices, alternatives, limitations |
| LANDSCAPE.md | **Written** | Other chess products, related work, differentiation |
| ROADMAP.md | **Written** | Future ideas, planned features |
| MATH.md | **Exists** | Theoretical/aspirational formalisms not yet implemented |
| TACTICS.md | **Exists** | User-facing explanation of tactical and positional detection |

---

## Shared Context for All Agents

### Project summary

Chess Teacher is a web application where a student plays chess against a
pedagogically-motivated opponent while receiving real-time coaching from an LLM.
The LLM never evaluates positions itself — it explains what Stockfish and coded
analysis functions find. A local RAG provides additional context from a knowledge
base of chess patterns and concepts.

### Key architectural facts

- **Server**: Python 3.14, FastAPI, python-chess, Stockfish (UCI), ChromaDB,
  Ollama (httpx client)
- **Browser**: TypeScript, chessground (board), stockfish.wasm (eval bar),
  snabbdom (virtual DOM), chess.js (move validation), esbuild (bundler)
- **Two Stockfish instances**: browser-side for responsive eval bar, server-side
  for the analysis pipeline
- **Deployment**: Docker on Xeon E5-1650 v4 (16GB RAM, ~4GB free); Ollama on
  remote 4070 Ti GPU

### Tone and style

- Technical but readable. Write for a developer or technically-inclined chess
  player, not a formal academic audience.
- Concrete over abstract. Prefer "the coach stays silent on routine moves" over
  "a pedagogical gating mechanism filters coaching interventions."
- Reference code by module/function name when relevant but don't reproduce code
  blocks unless they clarify a design concept.
- Each document should stand alone — a reader can start with any page. Use
  cross-references (`see [ARCHITECTURE.md](ARCHITECTURE.md)`) rather than
  assuming the reader has read other documents.

### Existing documents to be aware of

- `guide/DESIGN-THEORY.md` — maps MATH.md formalisms to code (position
  representation, CPDG, motifs, tactic diffing, game tree, ray walker)
- `guide/MATH.md` — theoretical framework for position description graphs
  (aspirational, not all implemented)
- `guide/TACTICS.md` — user-facing explanation of every tactical and positional
  motif the system detects

---

## 1. DESIGN.md — Hub Document

### Purpose

The entry point for all design documentation. A reader should finish this page
understanding what Chess Teacher is, why it exists, and where to go for details.

### Structure

1. **What is Chess Teacher** — one paragraph. A chess coaching application that
   combines Stockfish analysis, coded position understanding, and LLM explanation
   to teach during live play.
2. **Why it exists** — the gap it fills. Current chess tools (engines, puzzle
   trainers, video courses) either give answers without explanation or explain
   without grounding in concrete analysis. Chess Teacher bridges this: the LLM
   explains, but Stockfish and coded analysis provide the facts.
3. **Core design principle** — the LLM is the teacher persona; it never
   evaluates positions itself. Stockfish provides ground truth, the position
   analyzer provides structured facts, and the LLM translates these into
   coaching.
4. **How the pieces fit together** — a brief (3-4 sentence) overview of the
   system with an architecture diagram linking to deeper docs.
5. **Document map** — a table or list of all guide documents with one-sentence
   descriptions and links.

### Source files to read

- `CLAUDE.md` (project description and architecture diagram)
- `docs/plans/2026-02-20-ux-requirements.md` (problem statement, user model,
  constraints sections)
- `guide/DESIGN-THEORY.md` (for cross-reference, not reproduction)

### What NOT to include

- Technical details belonging in ARCHITECTURE.md or ANALYSIS-PIPELINE.md
- UI specifics belonging in UI.md
- Full feature descriptions belonging in topic pages

### Length target

~150-250 lines. Brief, linking, inviting.

---

## 2. PEDAGOGY.md — Teaching Philosophy

### Purpose

Describe how Chess Teacher teaches — the coaching model, when and why the coach
speaks, how it adapts to student level, and how the teachability system works.
This is the soul of the project.

### Structure

1. **Teaching philosophy** — learn by doing, not by memorizing. The student
   plays real games and receives coaching at moments that matter. Silence is
   approval.
2. **When the coach speaks** — trigger conditions: critical mistakes, key
   decision points, repertoire moments, good moves worth reinforcing, pattern
   repetition. Include the delegation table from UX requirements.
3. **What the coach says** — the LLM receives structured analysis (not raw
   positions) and translates it into explanations. It cannot invent tactics —
   only explain what the analysis found.
4. **ELO adaptation** — the five profiles (beginner through competitive), what
   varies between them (analysis depth, concept depth, centipawn threshold,
   coaching verbosity). How the opponent adjusts its play.
5. **Teachability ranking** — how the system decides which alternative moves are
   worth showing. The heuristic scores moves by new motif types per ply,
   material changes, and evaluation swings.
6. **Coaching intensity** — the autonomy gradient (guide me / watch me / let me
   play). How the system adapts implicitly.
7. **The Socratic sequence** — ask → hint → explain → never lecture unprompted.
   (Note: MVP implements explain-only; the full sequence is a future target.)
8. **What grounds the coaching** — Stockfish provides evaluation, coded analysis
   provides tactical/positional facts, the LLM provides language. The LLM never
   evaluates positions or invents analysis.

### Source files to read

- `docs/plans/2026-02-20-ux-requirements.md` (delegation design, coaching
  triggers, autonomy gradient, Socratic sequence, MVP cuts)
- `src/server/elo_profiles.py` (EloProfile dataclass, profile definitions)
- `src/server/coach.py` (assess_move, move classification, when coach speaks)
- `src/server/game_tree.py` (`_rank_nodes_by_teachability` function)
- `src/server/opponent.py` (phase-aware opponent move selection)
- `src/server/prompts/system.py` (COACHING_SYSTEM_PROMPT — what the LLM is
  told, failure mode sections)

### Cross-references to include

- ANALYSIS-PIPELINE.md for how analysis becomes a coaching prompt
- DESIGN-THEORY.md for the motif detection formalism
- ROADMAP.md for the trained teachability model (future)

### Length target

~200-350 lines.

---

## 3. UX.md — User Experience

### Purpose

Document the user interaction flows, user stories, and interaction model. How a
user experiences Chess Teacher from opening the app to finishing a game.

### Structure

1. **User model** — who uses this (800-1800 Elo players studying openings and
   positional concepts), their context, expertise, emotional job
2. **Core interaction loop** — student selects topic → plays game → receives
   coaching at critical moments → post-game summary
3. **User flows** — step-by-step for key scenarios:
   - Starting a new game (ELO selection, topic/repertoire)
   - Making a move and receiving coaching
   - Making a mistake and seeing the coach intervene
   - Playing a good move and receiving reinforcement
   - Opponent move selection (how it differs from a pure engine)
   - Game ending and review
4. **API interaction model** — how the frontend talks to the server (JSON API,
   key endpoints, request/response cycle for a move)
5. **Student disagreement** — student can always play any move. Coach
   acknowledges, lets play continue, revisits if trouble emerges.
6. **Alternative line exploration** — rewinding to explore "what if I had
   played..." (future feature)
7. **Failure handling** — degradation layers (full → no RAG → no LLM → no
   server Stockfish → no browser Stockfish), what the user sees at each level
8. **Success criteria** — response times, silence ratio, game start speed

### Source files to read

- `docs/plans/2026-02-20-ux-requirements.md` (comprehensive UX spec — this is
  the primary source)
- `src/server/main.py` (API endpoints, request/response models)
- `src/server/game.py` (GameManager, make_move flow, _enrich_coaching)
- `src/frontend/game.ts` (GameController — frontend game flow)
- `src/frontend/api.ts` (API client)

### What NOT to include

- Visual design details (colors, typography, layout) — those go in UI.md
- Pedagogical rationale — that goes in PEDAGOGY.md
- Implementation details of the analysis pipeline — ANALYSIS-PIPELINE.md

### Length target

~250-400 lines.

---

## 4. UI.md — User Interface

### Purpose

Document the visual design, layout, component structure, and frontend
architecture of the interface.

### Structure

1. **Design direction** — warmth and approachability blended with utility.
   Warm in the coaching panel, clean and functional around the board.
2. **Color palette** — dark foundation (#1a1a2e background, #16213e panels),
   light text (#e0e0e0), green accent (#4ade80). Rationale for dark theme
   (chess boards look best dark, matches Lichess convention).
3. **Typography** — geometric sans for UI, monospace for notation and eval.
4. **Layout** — split panel: coaching panel left, board + eval bar right.
   Header with title and hamburger menu. Move list. Describe the spatial
   hierarchy.
5. **Component structure** — the key UI components and their responsibilities:
   - Chessground board (piece rendering, drag interaction, arrows, highlights)
   - Eval bar (browser Stockfish, vertical bar)
   - Coaching panel (LLM commentary, scrolling)
   - Hamburger menu (new game, ELO selector, FEN input)
   - Move list
6. **Board annotations** — chessground arrows and square highlights. Green =
   good, red = warning. Sparse (1-2 key ideas).
7. **Frontend tech** — TypeScript, snabbdom (virtual DOM, ~3KB), esbuild
   (bundler), no framework. Why this stack (minimal, fast, no runtime overhead).
8. **Chessground integration** — cburnett SVGs base64-encoded in CSS (no
   external requests), piece dragging, promotion dialog.
9. **Responsive considerations** — current state and any adaptations.
10. **COEP/COOP headers** — required for SharedArrayBuffer (stockfish.wasm
    threading), applied as FastAPI middleware.

### Source files to read

- `docs/plans/2026-02-20-ux-requirements.md` (visual design section, layout
  diagram)
- `static/index.html` (inline CSS, dark theme, full layout)
- `src/frontend/main.ts` (app initialization, layout construction, hamburger
  menu)
- `src/frontend/board.ts` (chessground integration)
- `src/frontend/game.ts` (GameController, UI state management)
- `src/frontend/eval.ts` (browser Stockfish, eval bar)
- `static/chessground.css` (board styling)
- `package.json` (frontend dependencies)

### Cross-references to include

- UX.md for interaction flows
- ARCHITECTURE.md for the browser-side architecture
- TRADE-OFFS.md for why snabbdom over React

### Length target

~200-350 lines.

---

## 5. ARCHITECTURE.md — Software Architecture

### Purpose

Document the system structure: server and browser components, module
responsibilities, data flow, integration points, and deployment model.

### Structure

1. **System overview** — architecture diagram showing browser ↔ server ↔
   Stockfish/RAG/LLM. Two runtime contexts with different jobs.
2. **Server architecture**
   - FastAPI application (main.py): endpoints, middleware, lifespan management
   - Module map: engine.py, game.py, coach.py, analysis.py, game_tree.py,
     report.py, descriptions.py, motifs.py, llm.py, rag.py, knowledge.py,
     opponent.py, elo_profiles.py, puzzles.py, prompts/
   - Module responsibilities (one sentence each)
   - Key singletons (engine, teacher, rag, games, puzzle_db)
3. **Browser architecture**
   - Module map: main.ts, game.ts, board.ts, eval.ts, api.ts
   - GameController as the central coordinator
   - Build pipeline (esbuild, TypeScript → static/app.js)
4. **Data flow** — request lifecycle for a player move (frontend → API →
   engine evaluation → analysis → game tree → report → RAG → LLM → response)
5. **Integration points**
   - Stockfish UCI (python-chess wrapper, retry on crash)
   - Ollama HTTP API (LLM generation, embedding)
   - ChromaDB (in-process, SQLite + hnswlib)
   - Puzzle DB (SQLite + FTS5, 5.7M Lichess puzzles)
6. **Deployment model** — Docker, Xeon server, remote Ollama GPU box, memory
   constraints
7. **Scalability considerations** — single-user MVP, what would need to change
   for multi-user (game session management, Stockfish process pooling, RAG
   isolation)
8. **Local vs. cloud LLM** — current architecture uses local Ollama; the
   interface (httpx client) could point at any OpenAI-compatible API

### Source files to read

- `CLAUDE.md` (architecture diagram, conventions)
- `docs/plans/2026-02-20-foundation-design.md` (architecture, tech choices,
  project layout, RAG design, deployment target)
- `src/server/main.py` (FastAPI app, middleware, lifespan, endpoints)
- `src/server/game.py` (GameManager)
- `src/server/engine.py` (EngineAnalysis)
- `src/server/llm.py` (ChessTeacher)
- `src/server/rag.py` (ChessRAG)
- `src/server/puzzles.py` (PuzzleDB)
- `src/frontend/main.ts` (app init)
- `src/frontend/game.ts` (GameController)
- `pyproject.toml` (Python dependencies)
- `package.json` (frontend dependencies)
- `flake.nix` (dev environment)
- `Dockerfile` (deployment)

### Cross-references to include

- ANALYSIS-PIPELINE.md for the detailed transformation chain
- TRADE-OFFS.md for technology choice rationale
- DESIGN-THEORY.md for the analysis formalism

### What NOT to include

- Detailed analysis pipeline internals (ANALYSIS-PIPELINE.md covers that)
- Visual design (UI.md)
- Pedagogical model (PEDAGOGY.md)

### Length target

~300-450 lines.

---

## 6. ANALYSIS-PIPELINE.md — The Transformation Chain

### Purpose

Document the pipeline that transforms a chess position into a coaching prompt.
This is the core intellectual machinery of the system — how raw board state
becomes structured analysis becomes natural language becomes LLM input.

### Structure

1. **Pipeline overview** — diagram showing the five stages: Stockfish → coded
   analysis → game tree → descriptions/report → LLM prompt
2. **Stage 1: Stockfish evaluation** — engine.py provides evaluation (score_cp,
   score_mate, best_move) and MultiPV analysis (multiple candidate lines with
   full PVs). This is the ground truth.
3. **Stage 2: Coded analysis** — analysis.py (pure functions, no Stockfish, no
   side effects) detects 15+ positional concepts: material, pawn structure, king
   safety, piece activity, mobility, center control, space, development, files/
   diagonals, and all tactical motifs. Returns typed dataclasses (PositionReport,
   TacticalMotifs, etc.).
4. **Stage 3: Game tree construction** — game_tree.py builds a GameTree rooted
   at the student's decision point. Two-pass construction: Phase 1 screens
   candidates via shallow MultiPV + teachability ranking; Phase 2 validates top
   candidates with deeper analysis. GameNode holds position, eval, parent/child
   links, and lazily-computed tactics.
5. **Stage 4: Description and report** — three layers:
   - Layer 1: motifs.py — MOTIF_REGISTRY maps each motif type to identity
     extraction (key_fn), natural-language rendering (render_fn), ray
     deduplication, and item caps
   - Layer 2: descriptions.py — describe_position() renders all active motifs
     into three buckets (threats, opportunities, observations); describe_changes()
     diffs parent/child tactics via structural key comparison
   - Layer 3: report.py — serialize_report() walks the GameTree via DFS,
     assembling sections (position context, student's move, alternatives with
     continuations, material results, warnings)
6. **Stage 5: RAG and LLM** — knowledge.py queries the RAG for relevant
   patterns; llm.py passes the assembled prompt to the LLM (Ollama) for
   natural-language coaching output
7. **Tactic diffing** — the key innovation: structural comparison by piece
   squares (not string labels) correctly distinguishes "the d7 pin persists"
   from "a new pin appeared on c6"
8. **What the LLM sees** — the LLM receives pre-analyzed, pre-described facts.
   No FEN strings, no raw evaluations, no hallucination surface for chess
   specifics.
9. **What the LLM does NOT see** — raw board state, engine output, internal
   scoring. The LLM cannot invent a fork the analysis didn't find.

### Source files to read

- `src/server/game.py` (lines 69-118: _enrich_coaching method — the pipeline
  orchestrator)
- `src/server/engine.py` (EngineAnalysis, evaluate, analyze_lines, LineInfo)
- `src/server/analysis.py` (analyze, analyze_tactics, PositionReport,
  TacticalMotifs — read the top-level docstring and function signatures, not all
  955 lines)
- `src/server/game_tree.py` (GameNode, GameTree, build_coaching_tree,
  _rank_nodes_by_teachability)
- `src/server/descriptions.py` (describe_position, describe_changes,
  diff_tactics, PositionDescription, TacticDiff)
- `src/server/motifs.py` (MotifSpec, MOTIF_REGISTRY, render_motifs,
  all_tactic_keys, _dedup_ray_motifs)
- `src/server/report.py` (serialize_report — read all of it, ~120 lines)
- `src/server/knowledge.py` (query_knowledge)
- `src/server/llm.py` (explain_move)
- `guide/DESIGN-THEORY.md` (for cross-reference to formal underpinnings)

### Cross-references to include

- DESIGN-THEORY.md for the formal motif/CPDG definitions
- TACTICS.md for the user-facing motif descriptions
- ARCHITECTURE.md for where this pipeline sits in the system
- PEDAGOGY.md for how the pipeline output feeds coaching decisions

### Length target

~300-450 lines. This is the most technically dense document.

---

## 7. TRADE-OFFS.md — Technology Choices

### Purpose

Document the significant technology and design choices, what alternatives were
considered, and what limitations the current choices impose. An honest accounting
of trade-offs, not a sales pitch.

### Structure

1. **Stockfish as ground truth** — why a traditional engine rather than a neural
   net (Lc0, Maia). Stockfish is fast, deterministic, well-understood, runs on
   CPU. Lc0 would need GPU time (already allocated to Ollama). Maia offers
   human-like evaluation but less reliable analysis.
2. **Local LLM via Ollama** — why local rather than cloud API (privacy, cost,
   latency control, no API rate limits). Trade-off: limited to models that fit
   on a 4070 Ti (~14B params). Currently using qwen2.5:14b.
3. **python-chess for analysis** — the standard Python chess library. Strengths:
   legal move generation, pin-aware move validation, Stockfish UCI integration.
   Limitation: no tactical detection beyond is_pinned() and attackers() — all
   fork/skewer/etc detection is our code.
4. **Coded analysis vs. LLM analysis** — why the position analyzer is coded
   Python, not LLM-generated. LLMs hallucinate chess analysis. Coded functions
   produce deterministic, testable facts. The LLM explains; it does not analyze.
5. **chessground + snabbdom vs. React/Vue** — minimal frontend stack. Chessground
   is the Lichess board library (battle-tested, accessible, feature-rich).
   snabbdom is ~3KB virtual DOM. No framework runtime overhead. Trade-off: less
   ecosystem support, more manual DOM management.
6. **ChromaDB for RAG** — embedded vector store, simple API. Trade-off: Python
   3.14 compatibility issue (pydantic v1), limited scale (adequate for thousands
   of chunks, not millions). The interface is designed for backend swapability.
7. **Vendored Lichess code** — tactical detection functions from lichess-puzzler
   vendored with AST-hash drift detection. Why vendor: upstream API is not
   stable, our needs are specific. Trade-off: maintenance burden of tracking
   upstream changes.
8. **Two Stockfish instances** — browser-side for responsive eval bar, server-
   side for analysis pipeline. Why not share: different latency requirements,
   different depth needs, WASM has threading constraints.
9. **Pseudo-legal tolerance** — the analysis uses board.attacks() (pseudo-legal,
   ignores pins) for aggregate measures but restricts to legal moves for critical
   queries. Trade-off: minor inaccuracies in center control / activity scores
   vs. significant complexity reduction.
10. **Dark theme only** — chess boards look best on dark backgrounds, matches
    Lichess convention, focused experience. No light mode planned.
11. **Hardware constraints** — Xeon E5-1650 v4 (16GB RAM, ~4GB free) forces
    conservative Stockfish hash sizes and limits concurrent analysis. Ollama on
    separate GPU box mitigates but adds network latency.

### Source files to read

- `CLAUDE.md` (conventions, architecture rationale)
- `docs/plans/2026-02-20-foundation-design.md` (technology choices tables,
  deployment target, RAG architecture, Lc0 discussion)
- `docs/plans/2026-02-20-ux-requirements.md` (constraints section, failure
  handling / degradation)
- `guide/DESIGN-THEORY.md` (Section 5 on pin-blindness / pseudo-legal
  tolerance)
- `src/server/engine.py` (retry logic, Stockfish integration)
- `src/server/llm.py` (graceful fallback pattern)
- `src/server/analysis.py` (top docstring: "Pure-function position analysis
  module. No Stockfish, no side effects.")
- `package.json` (frontend deps — note what's NOT there: React, Vue, etc.)

### Cross-references to include

- ARCHITECTURE.md for system structure context
- ANALYSIS-PIPELINE.md for the coded-analysis design rationale
- LANDSCAPE.md for competitive context on the choices

### Length target

~250-400 lines.

---

## 8. LANDSCAPE.md — Related Work

### Purpose

Situate Chess Teacher in the broader landscape of chess software. What exists,
what it does well, what it doesn't do, and where Chess Teacher fits.

### Structure

1. **Chess engines** — Stockfish, Lc0. Provide evaluation but no explanation.
   Raw engine output is not coaching.
2. **Analysis platforms** — Lichess analysis board, Chess.com game review.
   Post-game analysis with engine annotations. Show what happened but often
   don't explain why in terms the student understands.
3. **Puzzle trainers** — Lichess puzzles, Chess Tempo, Chessable tactics.
   Isolated tactical exercises. Good for pattern recognition but divorced from
   game context.
4. **Course platforms** — Chessable, Chess.com lessons, ChessBase. Structured
   curricula, video instruction. High-quality but passive — the student watches
   or memorizes, not plays.
5. **AI chess tutors** — emerging space. Various ChatGPT/LLM chess bots. Most
   have no grounding — the LLM tries to evaluate positions and hallucinates.
   Chess Teacher's differentiator: the LLM never evaluates, only explains
   grounded analysis.
6. **Lichess relationship** — Chess Teacher uses several Lichess ecosystem
   components (chessground, puzzler tactical detection, puzzle database) and
   could integrate further (study export, game import). Lichess as open-source
   chess infrastructure.
7. **The gap Chess Teacher fills** — existing tools either give answers without
   explanation (engines), explain without grounding (LLM bots), or teach
   passively (courses). Chess Teacher grounds LLM explanation in engine analysis
   and delivers it during live play.

### Source files to read

- `CLAUDE.md` (project description)
- `docs/plans/2026-02-20-ux-requirements.md` (problem statement)
- `docs/plans/2026-02-20-foundation-design.md` (Lichess integration section)
- `src/server/lichess_tactics/` (vendored Lichess code — just note it exists)
- `src/server/puzzles.py` (Lichess puzzle database integration)

### Research instructions

The agent should supplement source files with its own knowledge of the chess
software landscape. This is the one document where external knowledge matters
more than reading code. Cover the major products (Lichess, Chess.com,
Chessable, Chess Tempo, ChessBase) and the emerging LLM-chess space.

### Cross-references to include

- DESIGN.md for the project's core value proposition
- TRADE-OFFS.md for why specific Lichess components were chosen

### Length target

~200-350 lines.

---

## 9. ROADMAP.md — Future Ideas

### Purpose

Document planned and speculative future features. Organized by proximity to
implementation (near-term, medium-term, speculative).

### Structure

1. **Near-term** — features that build directly on existing infrastructure:
   - Alternative LLM models (qwen3:8b, qwen3:4b — compare on eval harness)
   - Trained teachability model (replace heuristic scoring with decision tree,
     requires collecting training data via coaching feedback endpoint)
   - Coaching feedback endpoint (thumbs up/down on coaching responses, collects
     training data for teachability model and prompt iteration)
2. **Medium-term** — features requiring significant new work:
   - Full Socratic coaching sequence (ask → hint → explain, requires
     conversation state management)
   - Adaptive coaching intensity (implicit level adjustment based on student
     performance patterns)
   - Alternative line exploration (board rewind, branching game state)
   - Game review for real opponent games (import PGN, run through analysis
     pipeline, produce annotated study)
   - Pattern tracking across games (persistent user model, concept mastery)
3. **Speculative** — ideas with no current implementation plan:
   - Graph-structured RAG (position DAG with color-normalized hashing,
     transposition-aware retrieval)
   - Browser extension for Lichess overlay (coaching panel on Lichess analysis
     page)
   - Lichess Study export (annotated PGN with arrows and commentary)
   - Lc0 integration (neural net evaluation as complement to Stockfish,
     pedagogically useful when engines disagree)
   - Multi-user support (game sessions, user accounts, persistent preferences)
4. **Research directions** — from MATH.md that could inform future features:
   - Tactic interaction graph (compound tactics sharing pieces)
   - Forcing sequence verification (AND/OR tree search beyond Stockfish depth)
   - Fragility metric (betweenness centrality for tactical structures)
   - Dynamic CPDG sequences (how the position graph evolves through a game)

### Source files to read

- `docs/plans/2026-02-20-ux-requirements.md` (MVP cuts section — full design
  vs. MVP shows what's planned)
- `docs/plans/2026-02-20-foundation-design.md` (graph-structured RAG section,
  Lichess integration section, Lc0 discussion)
- `guide/MATH.md` (Section 10: open questions; sections on unimplemented
  concepts)
- `guide/DESIGN-THEORY.md` (final section: "What Remains in MATH.md Only")
- `src/server/game_tree.py` (`_rank_nodes_by_teachability` — the heuristic to
  be replaced)

### Cross-references to include

- PEDAGOGY.md for the coaching features being extended
- ARCHITECTURE.md for what infrastructure exists to build on
- MATH.md for the theoretical foundations of research directions

### Length target

~200-300 lines.

---

## 10. DESIGN-THEORY.md — Already Exists

Located at `guide/DESIGN-THEORY.md`. Maps formal concepts from MATH.md to their
code implementations. Covers position representation, the implicit CPDG, motif
detection, tactic identity and diffing, pin-blindness, game tree construction,
and complexity bounds.

**No agent needed.** This document is complete.

---

## 11. MATH.md — Already Exists

Located at `guide/MATH.md`. Theoretical framework for Chess Position Description
Graphs. Contains formal definitions, proofs, and open questions. Concepts here
are aspirational — they describe the mathematical structure that could underlie
the system, not what is currently implemented. DESIGN-THEORY.md serves as the
bridge, noting which MATH.md concepts are realized and which remain theoretical.

**No agent needed.** This document is complete.

---

## 12. TACTICS.md — Already Exists

Located at `guide/TACTICS.md`. User-facing explanation of every tactical and
positional motif the system detects. Covers forks, pins, skewers, discovered
attacks, double checks, x-rays, hanging/trapped/overloaded pieces, capturable
defenders, checkmate patterns, and positional concepts (material, pawn structure,
king safety, mobility, center control, space, development, files/diagonals, back
rank weakness, exposed king, mate threats).

**No agent needed.** This document is complete.

---

## Execution Notes

- Each document can be written independently and in parallel.
- Agents should read their listed source files before writing.
- Cross-references use relative markdown links: `[ARCHITECTURE.md](ARCHITECTURE.md)`.
- Documents live in `guide/` alongside the existing files.
- Do not reproduce content from existing documents — cross-reference instead.
- DESIGN.md should be written last (or revised after the others exist) since it
  links to all other documents. Alternatively, write it with placeholder links
  that will resolve once all documents are in place.
