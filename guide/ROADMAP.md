# Roadmap

Planned and speculative features, organized by proximity to implementation.
Near-term items build on existing infrastructure. Medium-term items require new
modules or architectural changes. Speculative items lack an implementation plan
but inform design decisions today.

For system architecture see [ARCHITECTURE.md](ARCHITECTURE.md). For the
mathematical framework underlying analysis see [MATH.md](MATH.md). For the
mapping between theory and code see [DESIGN-THEORY.md](DESIGN-THEORY.md).

---

## 1. Near-Term

These features build on existing modules and infrastructure. The work involves
tuning, measurement, and small additions to existing interfaces.

### 1.1 Alternative LLM Models

The coaching pipeline runs qwen2.5:14b on a remote 4070 Ti via Ollama. Two
smaller models -- qwen3:8b and qwen3:4b -- deserve evaluation. The 14b model
approaches the GPU's VRAM ceiling; a smaller model with comparable coaching
quality would reduce latency and free memory for other services.

**What exists:** The eval harness (15 coaching scenarios with graded pass/fail)
provides measurement infrastructure. `llm.py` calls `explain_move()` with a
structured prompt from `serialize_report()` in `report.py` -- the model name
is a configuration parameter.

**What to do:** Run each model through the eval harness. Compare coaching
accuracy (does the response identify the right concept?), severity calibration
(does it say "blunder" for blunders, not for inaccuracies?), notation accuracy
(does it reference the correct squares and pieces?), and latency
(time-to-first-token and total generation time).

### 1.2 Coaching Feedback Endpoint

Add thumbs up/down feedback on each coach message, with optional free-text
comment. This serves two purposes: prompt iteration (which scenarios does the
current prompt fail on?) and training data collection for the teachability
model (Section 1.3).

**What exists:** The coaching panel already renders coach messages. The game
session tracks the position, the student's move, and the coaching prompt --
all context needed to log a feedback event.

**What to build:** A `POST /api/feedback` endpoint accepting session ID, move
number, rating (up/down), and optional comment. Store in SQLite alongside the
prompt, the model's response, and the position FEN. Session-scoped storage
suffices for initial data collection; no user accounts needed.

### 1.3 Trained Teachability Model

Replace the heuristic scoring in `_rank_nodes_by_teachability()` (in
`game_tree.py`) with a learned model. The current heuristic assigns fixed
point values: 3.0 per early motif, 100.0 for checkmate, 4.0 for sacrifice
detection, -2.0 per deep-only motif. Hand-tuned during Sprint 6, these weights
work reasonably but cannot capture feature interactions (a fork that also
creates a passed pawn teaches more than the sum of its parts).

**Approach:** Collect coaching feedback (Section 1.2). Extract features from
each `GameNode` at decision points: motif counts by type and depth, eval
swing, material delta, sacrifice flag, pawn structure flags, game phase. Train
a decision tree or small gradient-boosted model to predict thumbs-up/down from
these features. The model replaces the linear scoring in
`_rank_nodes_by_teachability()` -- same interface, better ranking.

**Dependencies:** Requires the feedback endpoint (Section 1.2) to collect
several hundred coaching interactions before the training set grows large
enough.

---

## 2. Medium-Term

These features require new modules, state management, or significant changes
to the interaction model. The UX requirements document lists them as post-MVP
upgrades.

### 2.1 Socratic Coaching Sequence

The current coaching mode explains only: the coach identifies a critical
moment and describes what happened. The full design calls for three steps: ask
a question, hint if the student answers incorrectly, then explain fully.

**What this requires:** Conversation state within a game session. The coach
must track that it asked "What do you think about the d5 square?", wait for
the student's response, evaluate it against the structured analysis, and
decide whether to hint or explain. This is a multi-turn interaction overlaid
on the game loop, not a single request-response.

**Architecture impact:** The LLM orchestrator gains a per-session conversation
buffer. The coaching endpoint changes from "position in, explanation out" to
"position + conversation history in, next coaching action out." The frontend
needs an input field in the coaching panel (currently display-only).

### 2.2 Adaptive Coaching Intensity

Adjust coaching implicitly based on student performance patterns. When the
student consistently handles pins but misses forks, the coach stops commenting
on pins and focuses on forks. The UX requirements describe three explicit
levels (Guide me / Watch me / Let me play) plus implicit adaptation within
each level.

**What this requires:** A session-level model of student performance by
concept. Track which motif types the student's moves handle correctly (played
a good move in a position with a fork) versus which they miss. Decay the
coaching trigger threshold for mastered concepts; raise it for frequently
missed ones.

**Architecture impact:** Extends the game session with a performance tracker.
The screening step in `build_coaching_tree()` already classifies move quality
(good, inaccuracy, mistake, blunder) -- adaptive coaching uses this
classification to update per-concept confidence scores that modulate whether
the coach speaks.

### 2.3 Alternative Line Exploration

Let the student rewind the board and explore "what if" branches. The student
asks "what if I had played Nf6?" and the coach shows the continuation,
explains the difference, then returns to the game.

**What exists:** `GameTree` already represents branching game state --
`decision_point.children` holds the played move and engine alternatives, each
with continuation chains. The data structure supports exploration. The gaps are
frontend interaction (rewind, branch, return) and state management to track
exploration versus live play.

**Architecture impact:** The frontend needs board state branching: display a
past position, let the student make moves in it, show continuations from the
game tree or request new analysis. The game session tracks an "exploration
stack" so the student can return to the live game.

### 2.4 Game Review for Real Opponent Games

Import a PGN from a game the student played against a real opponent (on
Lichess, Chess.com, or over the board). Run it through the full analysis
pipeline -- Stockfish evaluation, tactical detection, game tree construction,
`serialize_report()` output -- and produce an annotated study highlighting
mistakes, missed tactics, and recurring positional themes.

**What exists:** The analysis pipeline (`analysis.py`, `game_tree.py`,
`descriptions.py`, `report.py`) targets single decision points. Game review
requires running this pipeline at every critical moment, then stitching
results into a coherent narrative.

**What to build:** A PGN import endpoint. A batch analysis mode that
identifies critical moments (eval swings beyond a threshold) across the full
game. A report aggregator that collects per-moment coaching output and
produces a summary. Output format: annotated PGN with natural-language
comments, suitable for display in the coaching panel or export to Lichess
Study.

### 2.5 Pattern Tracking Across Games

Track which positional and tactical concepts the student encounters and
handles correctly across multiple games. Build a user model that records
concept mastery over time: "You've seen 12 pin positions and handled 9 well.
You consistently miss knight forks on the queenside."

**What this requires:** Persistent user identity (at minimum, a local profile
or session token). A concept tracking store that records (concept, position
FEN, student move, outcome) tuples across sessions. Aggregation logic to
produce mastery summaries.

**Architecture impact:** This founds personalized coaching. The RAG system
could prioritize positions involving concepts the student struggles with. The
opponent move selection could prefer positions that exercise weak concepts.
Both require the user model as input.

---

## 3. Speculative

Ideas discussed in design documents but lacking an implementation plan. They
inform architectural decisions (keeping interfaces flexible, preserving future
directions) but appear on no sprint backlog.

### 3.1 Graph-Structured RAG

The current RAG architecture embeds flat text chunks into ChromaDB. The
foundation design document describes an alternative: a directed acyclic graph
of position nodes. Each node holds a position with a natural-language
description (the embedding target), engine evaluation, and graph edges to
parent positions, child continuations, and transposition equivalents.

Color-normalized retrieval via `board.mirror()` maps structurally equivalent
positions (same pawn structure, opposite colors) to one canonical form,
enabling cross-color pattern matching: "this is the same isolated d-pawn
structure you saw as White, but now you're on the other side."

**Why it matters:** Chess knowledge forms a position DAG, not flat text.
Structure-aware retrieval answers questions like "how did we get here?" (walk
ancestors), "what are the critical replies?" (walk children), and "where else
does this structure appear?" (follow transpositions). Semantic search finds the
neighborhood; graph traversal provides depth.

**Why speculative:** The current RAG handles coaching scenarios well enough.
Graph-structured retrieval adds complexity (graph storage, edge maintenance,
traversal queries) without a clear pedagogical payoff until the content library
grows large enough to benefit from structural navigation.

### 3.2 Browser Extension for Lichess Overlay

A lightweight browser extension that adds the coaching panel to Lichess's
analysis page. The extension communicates with the same FastAPI backend. The
student analyzes a position on Lichess and sees coaching commentary alongside
the native UI.

**Challenges:** COEP/COOP cross-origin restrictions prevent direct API calls
from the content script; requests must route through the extension's background
script. Lichess's DOM offers no stable API -- the extension needs careful
selectors and version tolerance.

### 3.3 Lichess Study Export

Export coaching analysis as Lichess Studies using annotated PGN with arrow
annotations (`[%cal ...]`) and highlighted squares (`[%csl ...]`). The
Lichess API supports study import via `POST /api/study/{id}/import-pgn`. This
leverages Lichess's study UI instead of reimplementing a full lesson viewer.
Students can revisit lessons on any device, share them, and produce output in a
standard format independent of Chess Teacher.

### 3.4 Lc0 Integration

Leela Chess Zero offers neural-network-based evaluation as a complement to
Stockfish's deep tactical search. The `EngineAnalysis` interface could support
multiple backends. Engine disagreements create pedagogical opportunities:
Stockfish may prefer a sharp tactical line while Lc0 favors a quiet positional
approach. Explaining *why* two strong engines disagree teaches evaluation
thinking.

**Practical constraint:** Lc0 requires GPU resources. The remote 4070 Ti
already runs Ollama (LLM + embeddings). Running Lc0 on the same GPU requires
time-sharing or a second GPU.

### 3.5 Multi-User Support

Game sessions, user accounts, persistent preferences. The application
currently operates single-user with no authentication. Multi-user support
enables pattern tracking (Section 2.5), leaderboards, shared studies, and
collaborative analysis. This is infrastructure, not a feature -- it unlocks
other features but provides no direct pedagogical value alone.

---

## 4. Research Directions

Concepts formalized in [MATH.md](MATH.md) that could inform future features.
These rest on theoretical ground but require research to determine whether they
produce pedagogical value in practice.

### 4.1 Tactic Interaction Graph

MATH.md Section 4.2 defines the tactic interaction graph I(P): a graph where
tactics are nodes and edges connect tactics that share pieces. Connected
components represent clusters of interrelated threats. A position with one
large connected component is "combinationally rich" -- many tactical threads
couple together.

**Potential application:** Compound tactic detection. When a knight
simultaneously creates a fork and serves as the blocker in a discovered
attack, the coaching explanation should present them as a unified combination,
not two independent observations. The interaction graph identifies these
couplings.

**Current gap:** The analysis pipeline detects each motif type independently.
No cross-motif analysis identifies shared pieces or coordinated threats.
Building I(P) requires post-processing the `TacticalMotifs` output to find
piece overlaps across motif instances.

### 4.2 Forcing Sequence Verification

MATH.md Section 6.2 describes verifying tactical soundness through AND/OR tree
search over forcing moves. The current system approximates soundness via
Stockfish evaluation: if the engine confirms an advantage after the tactic, it
treats the tactic as sound. Explicit forcing-line search would verify that the
advantage holds against all opponent responses, not just the engine's top line.

**Potential application:** Distinguishing real tactics from phantom patterns. A
fork where the opponent can capture the forking piece and defend both targets
simultaneously appears structurally but fails tactically. Proof-number search
(Allis et al., 1994) provides an efficient verification algorithm, converging
quickly when forcing moves have a small branching factor.

**Why research:** Stockfish depth already serves as a reasonable soundness
oracle for most positions. The cases where explicit forcing-line search
improves on deep engine evaluation remain unclear. The cost-benefit tradeoff
needs empirical study.

### 4.3 Fragility Metric

Barthelemy (2025) defines fragility as betweenness-centrality-weighted attack
counts. Empirically, fragility peaks around move 15-16 in master games and
follows a universal decay curve independent of player strength. A per-position
fragility score could signal to the coach that "this is a critical moment"
before any specific tactic appears.

**What it requires:** Computing betweenness centrality on the position
description graph. The graph exists implicitly (computed by `analysis.py`
functions) but needs materialization as an explicit graph object for centrality
computation. NetworkX or a lightweight graph library could serve.

### 4.4 Dynamic CPDG Sequences

A game produces a sequence of position description graphs G(P_0), G(P_1),
..., G(P_n). Studying this sequence as a dynamic graph -- tracking edge
births, deaths, and transformations across moves -- could reveal strategic
patterns: when does tactical complexity build? When does it dissipate? Do
signatures predict decisive moments?

MATH.md Section 10 notes that Sato et al. (2017) formalized this for Go as
graph transformations. The chess analog remains undeveloped. This is the most
speculative research direction: it requires both graph materialization and
temporal analysis tooling, with uncertain pedagogical payoff.

---

## Dependencies and Sequencing

Some items depend on others:

```
Feedback endpoint (1.2)
  └─> Trained teachability model (1.3)
        └─> Adaptive coaching (2.2)

Socratic coaching (2.1)
  └─> Adaptive coaching (2.2)

Game review (2.4)
  └─> Lichess Study export (3.3)

Pattern tracking (2.5)
  └─> Multi-user support (3.5)
  └─> Graph-structured RAG (3.1)
```

Near-term items (Section 1) are independent and can proceed in parallel,
except that the teachability model depends on feedback data. Medium-term items
mostly require the near-term foundation. Speculative items are independent
explorations.

The alternative LLM evaluation (1.1) demands the least effort and most likely
produces immediate benefit. The feedback endpoint (1.2) offers the highest
leverage: it creates the data foundation for multiple downstream features.
