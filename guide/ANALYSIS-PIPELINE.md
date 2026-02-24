# Analysis Pipeline

Every coaching message starts the same way: a chess position and a
student's move enter one end of the pipeline, and a grounded,
fact-checked natural-language explanation comes out the other. The
pipeline's job is to ensure the LLM never sees a raw position. It
receives pre-analyzed, pre-described facts -- structured text it can
reference but cannot hallucinate about.

This document traces that transformation chain from Stockfish
evaluation through coded analysis, game tree construction, description
rendering, and report serialization to the final LLM prompt. For
system architecture see [ARCHITECTURE.md](ARCHITECTURE.md). For the
formal design theory see [DESIGN-THEORY.md](DESIGN-THEORY.md).

```
Board + Student Move
        │
        ▼
┌───────────────────┐
│  1. Stockfish      │  engine.py
│     Evaluation     │  Ground truth: scores, PVs, mate threats
└────────┬──────────┘
         ▼
┌───────────────────┐
│  2. Coded          │  analysis.py
│     Analysis       │  Pure functions: material, pawns, tactics, ...
└────────┬──────────┘
         ▼
┌───────────────────┐
│  3. Game Tree      │  game_tree.py
│     Construction   │  Two-pass search, teachability ranking
└────────┬──────────┘
         ▼
┌───────────────────┐
│  4. Description    │  motifs.py, descriptions.py, report.py
│     & Report       │  Motif rendering, tactic diffs, sectioned text
└────────┬──────────┘
         ▼
┌───────────────────┐
│  5. RAG + LLM      │  knowledge.py, llm.py
│     Coaching       │  Semantic search, system prompt, explanation
└───────────────────┘
```

The pipeline orchestrator is `GameManager._enrich_coaching()` in
`game.py`. It calls each stage in sequence under a 20-second timeout
so the game never freezes waiting for analysis or the LLM.


## 1. Stockfish Evaluation

Stockfish provides ground truth. The analysis pipeline never guesses
whether a move is good or bad -- it asks the engine.

`EngineAnalysis` in `engine.py` wraps the Stockfish UCI binary behind
an async lock (Stockfish is single-threaded, so concurrent requests
queue rather than corrupt state). Three entry points matter for
coaching:

| Function | Returns | Used for |
|---|---|---|
| `evaluate()` | `Evaluation` | Single-depth score + best move |
| `analyze_lines()` | `list[LineInfo]` | MultiPV candidates with full PVs |
| `find_mate_threats()` | `list[dict]` | Mate-in-N threat detection |

`Evaluation` carries `score_cp` (centipawns) and `score_mate`
(distance to mate), always from White's perspective. Every downstream
consumer must adjust for student color -- a positive score is good for
White, not necessarily for the student.

`LineInfo` adds the full principal variation (`pv`) as a list of UCI
moves, giving the game tree builder material to construct continuation
chains.

Crash recovery lives in `_analyse_with_retry()`: if Stockfish dies
mid-analysis, the wrapper restarts the process and retries once before
propagating the error. This keeps a single engine crash from killing
an entire coaching interaction.

Mate threats get special treatment. `find_mate_threats()` evaluates
every legal move at the decision point looking for forced mate
sequences up to mate-in-3. These feed into the game tree as enriched
`MateThreat` objects via `enrich_node_mate_threats()`, giving the
description layer concrete threats to report.


## 2. Coded Analysis

`analysis.py` is roughly 1,000 lines of pure functions. No Stockfish,
no side effects, no network calls. Given a `chess.Board`, it returns a
`PositionReport` -- a complete snapshot of everything structurally
true about the position. The LLM teacher uses these structured facts
instead of hallucinating about positions.

`analyze(board)` orchestrates ten analysis categories:

| Category | Function | What it finds |
|---|---|---|
| Material | `analyze_material()` | Piece counts, imbalance, bishop pair |
| Pawn structure | `analyze_pawn_structure()` | Isolated, doubled, passed, backward, chains |
| King safety | `analyze_king_safety()` | Pawn shield, open files, danger score |
| Piece activity | `analyze_activity()` | Per-piece mobility, centralization |
| Tactical motifs | `analyze_tactics()` | 15 motif types in `TacticalMotifs` |
| Files & diagonals | `analyze_files_and_diagonals()` | Open files, connected rooks, long diagonals |
| Center control | `analyze_center_control()` | Pin-aware square control counts |
| Development | `analyze_development()` | Minor pieces off starting squares |
| Space | `analyze_space()` | Territory control on central files |
| Game phase | `detect_game_phase()` | Opening, middlegame, or endgame |

The tactical motifs system detects 15 types: pins (absolute and
relative), forks, skewers, hanging pieces, discovered attacks, double
checks, trapped pieces, mate patterns (11 named patterns from
back rank to smothered), mate threats, back rank weaknesses, x-ray
attacks, exposed kings, overloaded pieces, and capturable defenders.

Detection relies on two sources. Ray-based motifs (pins, skewers,
x-rays, discovered attacks) use `_find_ray_motifs()`, a single-pass
walker that iterates over every slider and every ray direction,
classifying each (slider, first-hit, second-hit) triple by color and
piece value. Hanging and trapped piece detection uses vendored Lichess
utilities (`is_hanging`, `is_trapped`) that provide x-ray-aware
capture logic matching Lichess's own puzzle engine. See
[TACTICS.md](TACTICS.md) for user-facing descriptions of every
motif the system detects.

Terminal positions (checkmate, stalemate) get empty stubs for
activity, space, and development -- those concepts are meaningless
when the game is over, and returning zeros prevents the description
layer from generating nonsense observations.


## 3. Game Tree Construction

The game tree converts flat engine lines into a navigable structure
the description layer can walk. `GameNode` is the single data
structure: a board, the move that reached it, parent/child links, an
engine evaluation, and lazily computed analysis caches (tactics and
full `PositionReport`).

`GameTree` provides decision-point context: the position where the
student chose a move. Its children include the student's actual move
(tagged `source="played"`) and engine alternatives (tagged
`source="engine"`), each with continuation chains.

### Two-pass construction

`build_coaching_tree()` builds the tree in two passes. The reason is
cost: deep Stockfish analysis is expensive, and most candidate moves
are uninteresting. Screening many candidates cheaply, then validating
only the best ones deeply, gives better results per second of engine
time.

**Pass 1 -- Screen wide.** `analyze_lines()` runs MultiPV at the
decision point with `screen_breadth` candidates at `screen_depth`
plies. Each candidate becomes a child node with a shallow
continuation chain.

**Teachability ranking.** `_rank_nodes_by_teachability()` scores each
candidate by walking its continuation chain and counting new tactical
motif types per ply. High-value motifs (double check, trapped piece)
score more. Sacrifices (material dip followed by recovery or mate)
get a bonus. Lines where tactics appear only at unreachable depth get
penalized. The heuristic sets `_interest_score` on each node.

**Pass 2 -- Validate deep.** The top `validate_breadth` candidates
receive deep evaluation at `validate_depth` plies. Their shallow
continuations are replaced with deep principal variations. All
non-validated engine nodes are pruned from the tree.

The student's actual move is added as a child of the decision point
with its own deep evaluation and continuation. If the student's move
matches an engine candidate, that node is re-tagged as "played"
rather than duplicated.

All depth and breadth parameters come from `EloProfile` in
`elo_profiles.py`. A beginner sees fewer, shallower alternatives
with more forgiving thresholds. A competitive player sees deeper
analysis with more alternatives. See
[PEDAGOGY.md](PEDAGOGY.md) for how these profiles shape the
coaching experience.


## 4. Motif Registry

The motif registry in `motifs.py` is the bridge between raw tactical
dataclasses and human-readable coaching text. Each motif type is one
`MotifSpec` entry in `MOTIF_REGISTRY`:

```
MotifSpec(
    diff_key, field, key_fn,
    render_fn, ray_dedup_key, cap,
    is_observation, priority, squares_fn
)
```

A single declaration per motif type drives four operations:

- **Identity keying** (`key_fn`): extracts a structural identity
  tuple -- e.g., `("pin", pinner_square, pinned_square)` -- used for
  tactic diffing across positions.
- **Rendering** (`render_fn`): converts a tactic instance and
  `RenderContext` into natural language with ownership labels
  ("your knight", "their rook").
- **Ray deduplication** (`ray_dedup_key`): when multiple motif types
  share a geometric ray, `_dedup_ray_motifs()` retains only the
  highest-priority classification. Priority order: absolute pin >
  relative pin > skewer > x-ray > discovered attack.
- **Item caps** (`cap`): discovered attacks and x-ray attacks are
  capped at 3 per rendering pass to prevent prompt flooding.

The registry currently holds 14 entries. Adding a new motif means
adding one `MotifSpec` entry plus one render function -- no changes
to the diffing, description, or report layers.


## 5. Position and Change Descriptions

`descriptions.py` is the natural-language description layer. It has
two entry points that the report serializer calls at each game tree
node.

**`describe_position(tree, node)`** answers "what does this position
look like?" It renders all active motifs through the registry and
categorizes them into three buckets:

- **Threats**: things bad for the student (opponent's pins, hanging
  student pieces, mate threats against the student).
- **Opportunities**: things good for the student (student's forks,
  opponent's hanging pieces, trapped opponent pieces).
- **Observations**: structural or latent motifs (back rank
  weaknesses, x-ray alignments, exposed kings).

Non-tactic positional observations are added separately: material
imbalance, isolated or passed pawns, open files near the king,
development status, rook placement, and pawn color complex
weaknesses. Phase-aware logic adjusts: endgame positions emphasize
king activity and passed pawns instead of development.

**`describe_changes(tree, node)`** answers "what changed?" It walks
the continuation chain from the parent position, diffs tactics at
each ply using `diff_tactics()`, and renders only new motifs. Future
plies (ply 1+) get threat wrapping: "White threatens 5.Nxe4,
discovered attack."


## 6. Tactic Diffing

Tactic diffing is what makes the coaching accurate about *change*.
Without it, the coach would describe every active tactic in a
position, most of which already existed before the student moved.

`diff_tactics()` in `descriptions.py` performs structural comparison
by piece squares, not string labels. Each tactic's identity is a
tuple extracted by its `key_fn` -- for a pin, that is
`("pin", pinner_square, pinned_square)`. Two pins are the same pin
if and only if they involve the same squares.

The diff produces three sets:

- **New** (`child_keys - parent_keys`): tactics that appeared after
  the move. These are what the coach should talk about.
- **Resolved** (`parent_keys - child_keys`): tactics that
  disappeared. The student broke a pin or escaped a fork.
- **Persistent** (`parent_keys & child_keys`): tactics unchanged
  by the move. The coach stays silent on these.

This matters because string-label comparison would conflate "the d7
pin persists" with "a new pin appeared on c6" -- both are "pin" as a
string, but they are different tactical situations. Square-based
identity distinguishes them correctly.

See [DESIGN-THEORY.md](DESIGN-THEORY.md) Section 4 for the formal
treatment of tactic identity and deltas.


## 7. Report Serialization

`serialize_report()` in `report.py` assembles the final LLM prompt
from the game tree. It walks the tree depth-first, calling
`describe_position()` and `describe_changes()` at each node, and
arranges the results into sections:

1. **Student color** -- so the LLM knows whose perspective to take.
2. **Game** -- PGN from root to decision point for move context.
3. **Position Before Move** -- three-bucket description of the
   decision point (threats, opportunities, observations).
4. **Student Move** -- classification (good/mistake/blunder),
   tactic changes, continuation with move numbers, material result,
   sacrifice or checkmate warnings.
5. **Alternatives** -- labeled "Stronger Alternative" for the best
   engine move when the student erred, "Also considered" for
   additional candidates, "Other option" when the student played
   well. Each gets its own changes, continuation, and result.
6. **Relevant chess knowledge** -- RAG context appended at the end.

Capture moves get explicit annotation: "bishop captures on f7
(Bxf7+)" rather than bare notation, because the coaching LLM
(qwen2.5:14b) sometimes misreads algebraic notation with "x" as
piece names.


## 8. RAG Enrichment

`knowledge.py` adds pedagogical context from the vector store.
`build_rag_query()` constructs a semantic search query tailored to
the move quality:

- **Blunder/mistake**: query focuses on tactical themes present
  (forks, pins, hanging pieces).
- **Inaccuracy**: query focuses on positional concepts (isolated
  pawns, passed pawns, activity imbalance).
- **Brilliant**: query focuses on what the student found.

`query_knowledge()` sends the query to ChromaDB via the RAG
interface, retrieves the top 3 results by semantic similarity, and
formats them with theme labels. The formatted text is appended to
the report as the "Relevant chess knowledge" section.

Graceful degradation: `query_knowledge()` wraps everything in a
try/except and returns empty string on any failure. If the RAG store
is empty, unreachable, or returns garbage, coaching proceeds with
engine analysis alone.


## 9. What the LLM Sees

The LLM receives two messages. The system prompt (defined in
`prompts/system.py`) establishes the coaching persona and constrains
behavior with explicit rules:

- Address the student as "you". Be concise: 2-3 sentences.
- ONLY mention pieces, squares, and tactics from the analysis.
- Use severity-appropriate language (no "a bit risky" for blunders).
- Respect the opportunity/threat classification directly.
- Use exact move notation from the analysis.

The user prompt is the output of `serialize_report()` -- structured
text with section headers, categorized observations, numbered move
continuations, and material results. No FEN strings. No raw
evaluation numbers. No board diagrams. Every fact is pre-computed and
pre-labeled.

`ChessTeacher.explain_move()` in `llm.py` sends both messages to
Ollama and returns the response. On any failure (network, timeout,
malformed response), it returns None and the game proceeds without
coaching.


## 10. What the LLM Does NOT See

The LLM never receives:

- Raw board state (FEN strings, bitboards, piece lists).
- Engine output (centipawn scores, principal variations, depth).
- Internal scoring (teachability scores, interest rankings).
- Motif dataclass internals (square indices, color booleans).
- Game tree structure (node links, continuation chains).

This is by design. The pipeline acts as a factual filter between the
chess position and the language model. Everything the LLM can say has
been pre-verified by Stockfish (is this move good?) and pre-described
by coded analysis (what tactics exist?). The LLM's job is
translation: turn structured facts into natural coaching language.

The alternative -- giving the LLM a FEN and asking it to analyze --
produces hallucinated tactics, incorrect square references, and
phantom piece locations. The pipeline exists specifically to prevent
that failure mode.
