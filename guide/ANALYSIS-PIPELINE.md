# Analysis Pipeline

A chess position and a student's move enter one end of the
pipeline; a grounded, fact-checked natural-language explanation
emerges from the other. The pipeline ensures the LLM never sees a
raw position. It receives pre-analyzed, pre-described facts --
structured text it can reference but cannot hallucinate about.

This document traces the transformation chain from Stockfish
evaluation through coded analysis, game tree construction,
description rendering, and report serialization to the final LLM
prompt. For system architecture see
[ARCHITECTURE.md](ARCHITECTURE.md). For the formal design theory
see [DESIGN-THEORY.md](DESIGN-THEORY.md).

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

`GameManager._enrich_coaching()` in `game.py` orchestrates the
pipeline. It calls each stage in sequence under a 20-second
timeout so analysis or the LLM never freezes the game.


## 1. Stockfish Evaluation

Stockfish provides ground truth. The pipeline never guesses
whether a move is good or bad -- it asks the engine.

`EngineAnalysis` in `engine.py` wraps the Stockfish UCI binary
behind an async lock (Stockfish is single-threaded, so concurrent
requests queue rather than corrupt state). Three entry points
serve coaching:

| Function | Returns | Purpose |
|---|---|---|
| `evaluate()` | `Evaluation` | Single-depth score + best move |
| `analyze_lines()` | `list[LineInfo]` | MultiPV candidates with full PVs |
| `find_mate_threats()` | `list[dict]` | Mate-in-N threat detection |

`Evaluation` carries `score_cp` (centipawns) and `score_mate`
(distance to mate), always from White's perspective. Every
downstream consumer must adjust for student color -- a positive
score favors White, not necessarily the student.

`LineInfo` adds the full principal variation (`pv`) as a list of
UCI moves, giving the game tree builder material for continuation
chains.

`_analyse_with_retry()` handles crash recovery: if Stockfish dies
mid-analysis, the wrapper restarts the process and retries once
before propagating the error. A single engine crash never kills
an entire coaching interaction.

Mate threats receive special treatment. `find_mate_threats()`
evaluates every legal move at the decision point, looking for
forced mate sequences up to mate-in-3. These feed into the game
tree as enriched `MateThreat` objects via
`enrich_node_mate_threats()`, giving the description layer
concrete threats to report.


## 2. Coded Analysis

`analysis.py` spans roughly 1,000 lines of pure functions. No
Stockfish, no side effects, no network calls. Given a
`chess.Board`, it returns a `PositionReport` -- a complete
snapshot of everything structurally true about the position. The
LLM teacher uses these structured facts instead of hallucinating
about positions.

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
relative), forks, skewers, hanging pieces, discovered attacks,
double checks, trapped pieces, mate patterns (11 named patterns
from back rank to smothered), mate threats, back rank weaknesses,
x-ray attacks, exposed kings, overloaded pieces, and capturable
defenders.

Detection draws on two sources. Ray-based motifs (pins, skewers,
x-rays, discovered attacks) use `_find_ray_motifs()`, a
single-pass walker that iterates over every slider and every ray
direction, classifying each (slider, first-hit, second-hit)
triple by color and piece value. Hanging and trapped piece
detection uses vendored Lichess utilities (`is_hanging`,
`is_trapped`) that provide x-ray-aware capture logic matching
Lichess's own puzzle engine. See [TACTICS.md](TACTICS.md) for
user-facing descriptions of every motif the system detects.

Terminal positions (checkmate, stalemate) get empty stubs for
activity, space, and development -- those concepts lose meaning
when the game ends, and returning zeros prevents the description
layer from generating nonsense observations.


## 3. Game Tree Construction

The game tree converts flat engine lines into a navigable
structure the description layer can walk. `GameNode` is the single
data structure: a board, the move that reached it, parent/child
links, an engine evaluation, and lazily computed analysis caches
(tactics and full `PositionReport`).

`GameTree` provides decision-point context: the position where the
student chose a move. Its children include the student's actual
move (tagged `source="played"`) and engine alternatives (tagged
`source="engine"`), each with continuation chains.

### Two-pass construction

`build_coaching_tree()` builds the tree in two passes because
deep Stockfish analysis costs time, and most candidate moves
teach nothing. Screening many candidates cheaply, then validating
only the best ones deeply, yields better results per second of
engine time.

**Pass 1 -- Screen wide.** `analyze_lines()` runs MultiPV at the
decision point with `screen_breadth` candidates at `screen_depth`
plies. Each candidate becomes a child node with a shallow
continuation chain.

**Teachability ranking.** `_rank_nodes_by_teachability()` scores
each candidate by walking its continuation chain and counting new
tactical motif types per ply. High-value motifs (double check,
trapped piece) score higher. Sacrifices (material dip followed by
recovery or mate) earn a bonus. Lines whose tactics appear only
at unreachable depth lose points. The heuristic sets
`_interest_score` on each node.

**Pass 2 -- Validate deep.** The top `validate_breadth`
candidates receive deep evaluation at `validate_depth` plies.
Deep principal variations replace their shallow continuations.
The tree drops all non-validated engine nodes.

The builder adds the student's actual move as a child of the
decision point with its own deep evaluation and continuation.
If the student's move matches an engine candidate, the builder
re-tags that node as "played" rather than duplicating it.

All depth and breadth parameters come from `EloProfile` in
`elo_profiles.py`. A beginner sees fewer, shallower alternatives
with more forgiving thresholds. A competitive player sees deeper
analysis with more alternatives. See
[PEDAGOGY.md](PEDAGOGY.md) for how these profiles shape the
coaching experience.


## 4. The Four-Layer Report Pipeline

After building the game tree, the system transforms it into natural-language text for the LLM through **four layers**, each with a single responsibility:

```
┌───────────────────────────────────────┐
│  Layer 4: Game Tree (game_tree.py)   │  Structure: nodes, links, evals
│  Data structure layer                 │
└───────────────┬───────────────────────┘
                ▼
┌───────────────────────────────────────┐
│  Layer 3: Motif Registry (motifs.py) │  Tactical rendering + chain detection
│  Declarative rendering layer          │
└───────────────┬───────────────────────┘
                ▼
┌───────────────────────────────────────┐
│  Layer 2: Descriptions (descriptions)│  Tactic diffs, position summaries
│  Change detection layer                │
└───────────────┬───────────────────────┘
                ▼
┌───────────────────────────────────────┐
│  Layer 1: Report (report.py)         │  DFS walk, sectioned text output
│  Orchestration layer                  │
└───────────────────────────────────────┘
                ▼
           Text prompt (LLM user message)
```

Each layer knows nothing about the layers above it. Layer 1 calls Layer 2, Layer 2 calls Layer 3, Layer 3 reads Layer 4. This separation allows independent testing and modification.

### Layer 4: Game Tree (game_tree.py)

**Responsibility:** Data structure holding the analyzed position tree.

The `GameTree` contains:
- **Root node** (`decision_point`): Position where the student chose a move
- **Played line** (`played`): The student's actual move with deep continuation
- **Engine alternatives** (`children` with `source="engine"`): Alternative moves with deep continuations
- **Lazy analysis caches**: Each `GameNode` computes `tactics` and full `PositionReport` on first access

**Key functions:**
- `build_coaching_tree()`: Two-pass construction (screen wide, validate deep)
- `rank_by_teachability()`: Score alternatives by pedagogical value using `TeachabilityWeights`
- `enrich_node_mate_threats()`: Add detected mate-in-N threats to nodes

Layer 4 is **chess-aware** but **language-agnostic**. It knows what a pin is (dataclass), but not how to describe one (text).

### Layer 3: Motif Registry (motifs.py)

**Responsibility:** Declarative motif rendering and tactical chain detection.

The `MOTIF_REGISTRY` is a dict mapping motif type strings (`"pin"`, `"fork"`, `"hanging"`, etc.) to `MotifSpec` entries. Each entry contains:
- **key_fn**: Function to create a unique key identifying this motif instance (for deduplication)
- **render_fn**: Function to produce human-readable text from the motif dataclass
- **diff_key**: Field name in `TacticalMotifs` (e.g., `"pins"`)
- **priority**: Rendering order (higher priority rendered first)
- **ray_dedup_key**: Optional function to deduplicate ray-based motifs (pins, skewers, x-rays)

**Rendering with chain integration:**
```python
def _render_pin(pin, student_is_white, is_tactic_after, chain_info):
    """Render a pin motif, optionally with inline chain consequence."""
    text = f"{your_their} {piece_name} on {pinned_sq} is pinned..."

    # Check for pin→hanging chain
    pin_key = ("pin", pin.pinner_square, pin.pinned_square, pin.pinned_to, pin.is_absolute)
    if pin_key in chain_info.get("pin_hanging", {}):
        hanging_key = chain_info["pin_hanging"][pin_key]
        text += f" (This pin leaves {describe_hanging(hanging_key)}.)"

    return text
```

**Tactical chain detection:**
- `_detect_pin_hanging_chains()`: Match pins against hanging pieces via `defense_notes`
- `_detect_overload_hanging_chains()`: Match overloaded pieces against hanging pieces
- `_detect_capturable_defender_chains()`: Match capturable defenders against hanging pieces

Layer 3 is **text-generating** but **structure-agnostic**. It renders one motif at a time, doesn't know about nodes or trees.

### Layer 2: Descriptions (descriptions.py)

**Responsibility:** Tactic diffing and position change detection.

`describe_changes()` compares two `TacticalMotifs` objects (before and after a move) and produces three lists:
- **New tactics**: Motifs present after the move but not before
- **Resolved tactics**: Motifs present before but not after
- **Persistent tactics**: Motifs present both before and after (unchanged)

**Key insight:** The system deduplicates motifs by **keying**, not by object identity. Two `Pin` objects with the same `(pinner_square, pinned_square, pinned_to, is_absolute)` tuple are considered identical, even if they come from different positions.

`describe_position()` produces a textual summary of a position:
- Material imbalance
- Pawn structure weaknesses (isolated, doubled, passed, backward)
- King safety (pawn shield, open files, danger score)
- Piece activity (centralized pieces, mobile pieces)
- Tactical motifs (sorted by priority and rendered via Layer 3)

**Tense control:**
`describe_position()` accepts a `tense` parameter (`"present"` or `"past"`). Past tense is used for "Position Before" sections (the decision point), present tense for "Position After" sections (after the student's move).

Layer 2 is **change-aware** but **section-agnostic**. It describes single positions and position pairs, doesn't know about DFS walks or coaching reports.

### Layer 1: Report (report.py)

**Responsibility:** DFS walk over the game tree and sectioned text output.

`serialize_report()` is the top-level orchestrator. It walks the `GameTree` and produces the coaching prompt as a structured text document:

**Sections:**
1. **Played Line Context**: Game history leading to the decision point
2. **Decision Point**: Position before the student's move (with tactics in past tense)
3. **Your Move**: The student's move with eval delta and positional changes
4. **Position After Your Move**: Tactical and positional situation after the move
5. **Alternative Moves**: Top N engine-suggested alternatives with continuations
6. **Positional Factors**: Material, king safety, pawn structure, piece activity

**Key functions:**
- `_append_continuation_analysis()`: Describe a single continuation line (move + tactics + eval)
- `_describe_capture()`: Annotate capture moves to prevent notation confusion ("bishop captures on f7 (Bxf7+)")
- `_format_pv_with_numbers()`: Add move numbers to continuation lines ("3. Nf3 Nc6 4. d4")
- `_append_categorized()`: Helper for bulleted lists ("New tactics:\n  - Pin: ...\n  - Fork: ...")

**Data flow:**
```python
def serialize_report(tree: GameTree, quality: str, cp_loss: int, rag_context: str = "") -> str:
    lines = []

    # Position Before Move (Layer 2 → Layer 3)
    pos_desc = describe_position(tree, decision, tense="past")
    _append_categorized(lines, "Threats", pos_desc.threats)
    _append_categorized(lines, "Opportunities", pos_desc.opportunities)

    # Student Move (Layer 2 diff)
    describe_changes(tree, player_node)  # diffs tactics at each ply
    _append_continuation_analysis(lines, player_node, ...)

    # Alternatives (recurse on children)
    for alt in top_alternatives:
        _append_continuation_analysis(lines, alt, ...)

    return "\n".join(lines)
```

Layer 1 is **structure-aware** but **LLM-agnostic**. It doesn't know about system prompts, personas, or RAG context — just produces a text report.

---

## Why Four Layers?

**Separation of concerns:** Each layer has a single job. Layer 1 doesn't render motifs, Layer 3 doesn't diff tactics, Layer 2 doesn't walk trees.

**Independent testing:** Each layer is testable in isolation:
- Layer 4: `test_game_tree.py` (teachability scoring, tree construction)
- Layer 3: `test_motifs.py` (rendering, chain detection, deduplication)
- Layer 2: `test_descriptions.py` (diffing, position summaries)
- Layer 1: `test_report.py` (section structure, DFS walk)

**Modular replacement:** Want to change how pins are rendered? Modify Layer 3. Want to add a new report section? Modify Layer 1. The layers don't cascade.

**No chess logic in orchestration:** Layer 1 contains zero chess-specific logic. It calls `describe_position()` and formats the result. All chess knowledge lives in Layers 2-4.

---

## Example: Pin→Hanging Chain Rendering

Let's trace a single tactical chain through all four layers:

**Position:** White knight on d4 defends pawn on f5. Black bishop on a1 pins knight to White king on h8.

### Layer 4: Game Tree
```python
node = tree.played
tactics = node.tactics  # Lazy-computed via analyze_tactics()
# tactics.pins = [Pin(pinner_square="a1", pinned_square="d4", pinned_to="h8", is_absolute=True)]
# tactics.hanging = [HangingPiece(square="f5", piece="P", color="white", value=TacticValue(...))]
```

### Layer 3: Motif Registry
```python
chains = _detect_pin_hanging_chains(tactics)
# chains = {("pin", "a1", "d4", "h8", True): ("hanging", "f5", "P", "white")}

# Render pin with chain
pin_key = ("pin", "a1", "d4", "h8", True)
text = _render_pin(pin, student_is_white=True, is_tactic_after=False, chain_info={"pin_hanging": chains})
# text = "Your knight on d4 is pinned to your king on h8 by their bishop on a1.
#         (This pin leaves your pawn on f5 hanging — worth ~1.0 pawns.)"
```

### Layer 2: Descriptions
```python
# describe_changes() calls Layer 3 to render new tactics
new_tactics = render_motifs(after_tactics, student_is_white, is_tactic_after=True, chains)
# new_tactics = ["Your knight on d4 is pinned... (This pin leaves your pawn on f5 hanging...)"]
```

### Layer 1: Report
```python
# serialize_report() assembles sections
lines.append("## Position After Your Move")
lines.append("New tactics:")
for tactic in new_tactics:
    lines.append(f"  - {tactic}")
# Output:
# ## Position After Your Move
# New tactics:
#   - Your knight on d4 is pinned to your king on h8 by their bishop on a1.
#     (This pin leaves your pawn on f5 hanging — worth ~1.0 pawns.)
```

The chain is **detected** in Layer 3, **rendered** in Layer 3, **categorized** in Layer 2, and **sectioned** in Layer 1.

---

## Extending the Pipeline

### Adding a New Motif Type

1. **Layer 4:** Add detection logic to `analysis.py` (e.g., `_detect_trapped_pieces()`)
2. **Layer 3:** Add `MotifSpec` entry to `MOTIF_REGISTRY` with render function
3. **Layer 2:** No changes (generic diffing handles all motif types)
4. **Layer 1:** No changes (DFS walk handles all motif types)

### Adding a New Report Section

1. **Layer 4:** No changes (data structure is generic)
2. **Layer 3:** No changes (renders individual motifs)
3. **Layer 2:** Possibly add new description function (e.g., `describe_endgame_factors()`)
4. **Layer 1:** Add new section logic to `serialize_report()`

### Adding a New Chain Type

1. **Layer 4:** No changes
2. **Layer 3:** Add chain detection function (e.g., `_detect_fork_discovered_chains()`) and integrate into rendering
3. **Layer 2:** No changes
4. **Layer 1:** No changes

---

## 4. Motif Registry (Layer 3 Deep Dive)

The motif registry in `motifs.py` bridges raw tactical dataclasses
and human-readable coaching text. Each motif type occupies one
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
  tuple -- e.g., `("pin", pinner_square, pinned_square)` -- for
  tactic diffing across positions.
- **Rendering** (`render_fn`): converts a tactic instance and
  `RenderContext` into natural language with ownership labels
  ("your knight", "their rook").
- **Ray deduplication** (`ray_dedup_key`): when multiple motif
  types share a geometric ray, `_dedup_ray_motifs()` retains only
  the highest-priority classification. Priority order: absolute
  pin > relative pin > skewer > x-ray > discovered attack.
- **Item caps** (`cap`): discovered attacks and x-ray attacks cap
  at 3 per rendering pass to prevent prompt flooding.

The registry holds 14 entries. Adding a new motif requires one
`MotifSpec` entry plus one render function -- no changes to the
diffing, description, or report layers.


## 5. Position and Change Descriptions

`descriptions.py` forms the natural-language description layer.
Two entry points serve the report serializer at each game tree
node.

**`describe_position(tree, node)`** answers "what does this
position look like?" It renders all active motifs through the
registry and sorts them into three buckets:

- **Threats**: dangers to the student (opponent's pins, hanging
  student pieces, mate threats against the student).
- **Opportunities**: advantages for the student (student's forks,
  opponent's hanging pieces, trapped opponent pieces).
- **Observations**: structural or latent motifs (back rank
  weaknesses, x-ray alignments, exposed kings).

Separate logic adds non-tactic positional observations: material
imbalance, isolated or passed pawns, open files near the king,
development status, rook placement, and pawn color complex
weaknesses. Phase-aware adjustments shift emphasis: endgame
positions highlight king activity and passed pawns instead of
development.

**`describe_changes(tree, node)`** answers "what changed?" It
walks the continuation chain from the parent position, diffs
tactics at each ply via `diff_tactics()`, and renders only new
motifs. Future plies (ply 1+) receive threat wrapping: "White
threatens 5.Nxe4, discovered attack."


## 6. Tactic Diffing

Tactic diffing makes coaching accurate about *change*. Without
it, the coach would describe every active tactic in a position,
most of which already existed before the student moved.

`diff_tactics()` in `descriptions.py` compares tactics by piece
squares, not string labels. Each tactic's identity is a tuple
extracted by its `key_fn` -- for a pin, that means
`("pin", pinner_square, pinned_square)`. Two pins are the same
pin if and only if they share the same squares.

The diff produces three sets:

- **New** (`child_keys - parent_keys`): tactics that appeared
  after the move. The coach talks about these.
- **Resolved** (`parent_keys - child_keys`): tactics that
  disappeared. The student broke a pin or escaped a fork.
- **Persistent** (`parent_keys & child_keys`): tactics unchanged
  by the move. The coach stays silent on these.

Square-based identity matters because string-label comparison
would conflate "the d7 pin persists" with "a new pin appeared on
c6" -- both read "pin" as a string, but they represent different
tactical situations.

See [DESIGN-THEORY.md](DESIGN-THEORY.md) Section 4 for the
formal treatment of tactic identity and deltas.


## 7. Report Serialization

`serialize_report()` in `report.py` assembles the final LLM
prompt from the game tree. It walks the tree depth-first,
calling `describe_position()` and `describe_changes()` at each
node, and arranges the results into sections:

1. **Student color** -- so the LLM knows whose perspective to
   take.
2. **Game** -- PGN from root to decision point for move context.
3. **Position Before Move** -- three-bucket description of the
   decision point (threats, opportunities, observations).
4. **Student Move** -- classification (good/mistake/blunder),
   tactic changes, continuation with move numbers, material
   result, sacrifice or checkmate warnings.
5. **Alternatives** -- labeled "Stronger Alternative" for the
   best engine move when the student erred, "Also considered"
   for additional candidates, "Other option" when the student
   played well. Each gets its own changes, continuation, and
   result.
6. **Relevant chess knowledge** -- RAG context appended last.

Capture moves get explicit annotation: "bishop captures on f7
(Bxf7+)" rather than bare notation, because the coaching LLM
(qwen2.5:14b) sometimes misreads algebraic notation containing
"x" as piece names.


## 8. RAG Enrichment

`knowledge.py` adds pedagogical context from the vector store.
`build_rag_query()` constructs a semantic search query tailored
to the move quality:

- **Blunder/mistake**: query targets tactical themes (forks,
  pins, hanging pieces).
- **Inaccuracy**: query targets positional concepts (isolated
  pawns, passed pawns, activity imbalance).
- **Brilliant**: query targets what the student found.

`query_knowledge()` sends the query to ChromaDB via the RAG
interface, retrieves the top 3 results by semantic similarity,
and formats them with theme labels. The formatted text joins the
report as the "Relevant chess knowledge" section.

`query_knowledge()` wraps everything in a try/except and returns
empty string on any failure. If the RAG store is empty,
unreachable, or returns garbage, coaching proceeds on engine
analysis alone.


## 9. What the LLM Sees

The LLM receives two messages. The system prompt (defined in
`prompts/system.py`) establishes the coaching persona and
constrains behavior with explicit rules:

- Address the student as "you". Stay concise: 2-3 sentences.
- Mention ONLY pieces, squares, and tactics from the analysis.
- Match severity to language (no "a bit risky" for blunders).
- Respect the opportunity/threat classification directly.
- Use exact move notation from the analysis.

The user prompt is the output of `serialize_report()` --
structured text with section headers, categorized observations,
numbered move continuations, and material results. No FEN
strings. No raw evaluation numbers. No board diagrams. Every
fact arrives pre-computed and pre-labeled.

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

This exclusion is deliberate. The pipeline acts as a factual
filter between the chess position and the language model.
Stockfish pre-verifies every claim (is this move good?); coded
analysis pre-describes every pattern (what tactics exist?). The
LLM translates structured facts into natural coaching language.

Giving the LLM a FEN and asking it to analyze would produce
hallucinated tactics, incorrect square references, and phantom
piece locations. The pipeline exists to prevent exactly that
failure mode.
