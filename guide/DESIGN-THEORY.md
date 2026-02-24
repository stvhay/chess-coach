# Design of the Chess Position Description Graph Implementation

This document extracts from [MATH.md](MATH.md) the concepts realized in the
Chess Teacher codebase. It preserves formal definitions and describes how they
map to code. Concepts that remain theoretical or aspirational live in MATH.md
only.

---

## 1. Position Representation

A **position** P = (Pi, gamma, kappa, epsilon) maps to a `chess.Board` object
encoding piece placement Pi, side to move gamma, castling availability kappa,
and en passant target epsilon -- the same information as a FEN string (MATH.md
Section 1.1).

The code stores pieces not as explicit (type, color, square) triples but
through bitboard-backed accessors: `board.piece_at(sq)`,
`board.attackers(color, sq)`, `board.attacks(sq)`. The projections type(p),
color(p), square(p) from Section 1.1 appear as properties of `chess.Piece` and
its associated square index.

### 1.1 Relationships Between Pieces

The binary relationships from MATH.md Section 1.2 map to code as follows:

| Relationship | Implementation |
|-------------|----------------|
| attacks(p_i, p_j) | `board.attacks(sq_i)` intersected with opponent piece squares |
| defends(p_i, p_j) | `board.attacks(sq_i)` intersected with friendly piece squares |
| blocks(p_i, p_j) | Implicit in ray-walk: first piece hit occludes second |
| pins(p_i, p_j, p_k) | `board.is_pinned(color, sq)` for detection; `_find_ray_motifs()` for classification |
| xrays(p_i, p_j, p_k) | `_find_ray_motifs()` classifies (slider, first_hit, second_hit) triples |

**Pseudo-legality remark.** As MATH.md Section 1.2 notes, `board.attacks()`
computes attack and defense edges pseudo-legally. For critical determinations
(sole defender, overloaded piece), the code restricts to legal moves via
`board.legal_moves` and `board.is_pinned()`. The design uses pseudo-legal
computation for aggregate measures and legal-move precision where correctness
demands it. See also Section 5 on pin-blindness.

---

## 2. The Position Description Graph

The CPDG G(P) = (V, E, lambda_V, lambda_E) from MATH.md Section 2.1 has no
explicit graph data structure. It exists implicitly: the node set V is the set
of pieces on the board, and the analysis functions in `analysis.py` compute the
edge set E on demand.

The labeled directed multigraph property holds: two pieces may share multiple
relationship types simultaneously (e.g., a piece that both attacks an enemy and
participates in a pin), and each relationship carries properties (e.g.,
`is_absolute` for pins, `significance` for discovered attacks).

### 2.1 Ternary Edges as Role-Labeled Structures

Ternary relationships (MATH.md Section 2.2) take the form of dataclasses with
named role fields, matching the tactic edge formalism tau = (mu, rho, E_tau):

```
Pin(pinner_square, pinned_square, pinned_to, pinner, pinned, is_absolute, color)
```

corresponds to rho = {pinner: p_1, pinned: p_2, shielded: p_3} with roles
projected to squares and pieces. The 15 tactical dataclasses in `analysis.py`
each encode one motif type with its role assignments.

### 2.2 Restriction

The r-restriction G_r(P) from MATH.md Section 2.3 works operationally:
`analyze_tactics()` returns a `TacticalMotifs` object whose fields partition
the edge set by relationship type (`.pins`, `.forks`, `.skewers`, etc.).
Accessing a single field restricts the graph to that edge type.

---

## 3. Motifs

### 3.1 Motif as Pattern Template

**Definition 3.1** from MATH.md defines a motif as M = (name, R_M, phi_M).
The `MotifSpec` dataclass in `motifs.py` realizes this:

| Formal element | MotifSpec field |
|---------------|----------------|
| name | `diff_key` (string identifier: "pin", "fork", "skewer", ...) |
| R_M (role set) | Implicit in the tactical dataclass fields (Pin has pinner, pinned, pinned_to) |
| phi_M (matching predicate) | Detection function in `analysis.py` (e.g., `_find_ray_motifs`, `_find_forks`) |

The separation between motif (detection rule) and tactic (instance) from
MATH.md Section 3.2 holds: `MotifSpec` defines *what to look for*, and the
detected objects (Pin, Fork, etc.) are the instantiated tactics tau.

### 3.2 Instantiation

A tactic tau = (M, rho, pi) instantiates a motif in a specific position
(MATH.md Section 3.2). Each detected object (e.g., a `Pin` instance) carries:

- The motif type (implicit in the dataclass type and `diff_key`)
- The role assignment rho (the square and piece fields)
- Properties pi (e.g., `is_absolute`, `significance`, `is_check_fork`)

`analyze_tactics(board)` computes the set **T**(P) of all tactics in a
position, returning a `TacticalMotifs` object containing lists of all detected
instances across all motif types.

### 3.3 Detection as Constrained Search

Motif detection follows the subgraph matching formulation of MATH.md
Section 3.3. For each motif type, the code searches for role assignments
satisfying the matching predicate:

- **Ray motifs** (pins, skewers, x-rays, discovered attacks): A single-pass
  unified walker `_find_ray_motifs()` iterates over each sliding piece and each
  ray direction, classifying the (slider, first_hit, second_hit) triple by
  color and piece value. This achieves the O(s * 8) complexity noted in
  Section 8.1.

- **Forks**: `_find_forks()` checks each piece's attack set for multiple
  enemy targets, counting a defended target only when the forker is worth less
  than the target or delivers check.

- **Hanging pieces**: Vendored Lichess utilities (`is_hanging`) provide
  x-ray-aware capture detection.

- **Overloaded pieces**: The detector checks for sole defenders carrying
  multiple duties (defending attacked friendly pieces, guarding the back rank,
  blocking mate threats).

The pattern graphs are small (2-5 nodes) and heavily constrained, as MATH.md
notes, making detection linear in practice despite the theoretical
NP-completeness of general subgraph isomorphism.

### 3.4 Motif Catalog

The 14 motif types in `MOTIF_REGISTRY` correspond to the catalog in MATH.md
Section 3.4, sharing the same role structures and matching predicates:

| MATH.md Motif | Registry diff_key | Detection function |
|--------------|-------------------|-------------------|
| Fork | "fork" | `_find_forks()` |
| Pin (absolute) | "pin" | `_find_ray_motifs()`, `is_absolute=True` |
| Pin (relative) | "pin" | `_find_ray_motifs()`, `is_absolute=False` |
| Skewer | "skewer" | `_find_ray_motifs()` |
| Discovered attack | "discovered" | `_find_ray_motifs()` |
| X-ray attack | "xray" | `_find_ray_motifs()` |
| Double check | "double_check" | `_find_double_checks()` |
| Hanging piece | "hanging" | `_find_hanging()` |
| Trapped piece | "trapped" | `_find_trapped_pieces()` |
| Overloaded piece | "overloaded" | `_find_overloaded_pieces()` |
| Capturable defender | "capturable_defender" | `_find_capturable_defenders()` |
| Mate patterns | "mate_pattern" | `_find_mate_patterns()` |
| Mate threat | "mate_threat" | `_find_mate_threats()` |
| Back rank weakness | "back_rank" | `_find_back_rank_weaknesses()` |
| Exposed king | "exposed_king" | `_find_exposed_kings()` |

`_find_ray_motifs()` detects x-ray defenses and stores them in
`TacticalMotifs.xray_defenses`, but the `MOTIF_REGISTRY` omits them
(they are neither rendered nor diffed).

---

## 4. Tactical Order and Diffing

### 4.1 Tactical Order

The tactical order T(P) = |**T**(P)| (MATH.md Section 4.1) equals the sum of
all list lengths in a `TacticalMotifs` object. No named field stores it; it
remains implicit.

### 4.2 Tactic Identity Across Positions

MATH.md Section 4.4 defines tactic identity by motif type and participating
piece squares. Each `MotifSpec`'s `key_fn` implements this directly, extracting
a structural identity tuple:

```python
# Pin identity: (diff_key, pinner_square, pinned_square)
key_fn=lambda t: ("pin", t.pinner_square, t.pinned_square)

# Fork identity: (diff_key, forking_square, sorted_target_squares)
key_fn=lambda t: ("fork", t.forking_square, tuple(sorted(t.targets)))
```

`all_tactic_keys(tactics)` in `motifs.py` computes the full set of identity
keys for a position, enabling set-theoretic operations.

### 4.3 Tactical Delta

The tactical delta Delta(m) and nabla Nabla(m) from MATH.md Section 4.3 live
in `diff_tactics()` in `descriptions.py`:

```python
TacticDiff(
    new_keys     = child_keys - parent_keys,    # Delta(m)
    resolved_keys = parent_keys - child_keys,   # Nabla(m)
    persistent_keys = parent_keys & child_keys  # unchanged
)
```

This structural comparison -- by key squares, not string labels -- is the
"more principled" approach described in MATH.md Section 4.4. It correctly
distinguishes "the d7 pin persists" from "a new pin appeared on c6."

---

## 5. Pin-Blindness

MATH.md Section 5.3 describes the pseudo-legal attack map issue: `board.attacks()`
ignores pins on the attacking piece, producing phantom defense edges. The code
addresses this in two ways:

1. **Legal-move restriction** for critical queries: overloaded-piece detection
   calls `_can_defend()` after `_is_sole_defender()`, which calls
   `board.is_pinned()` to exclude pinned pieces from the defender count.

2. **Pseudo-legal tolerance** for aggregate measures: center control, space
   calculation, and activity assessment use `board.attacks()` directly,
   accepting the approximation as MATH.md describes.

---

## 6. Soundness via the Game Tree

### 6.1 The Game Tree

MATH.md Sections 6.2-6.4 describe verifying tactical soundness through forcing
sequences searched in a game tree. `GameTree` and `GameNode` in `game_tree.py`
provide the structural framework.

A `GameNode` holds a position (board), the move that reached it, a Stockfish
evaluation (score_cp, score_mate), lazily computed tactics, and parent/child
links. The `GameTree` provides decision-point context: the position where the
student must choose a move.

### 6.2 Two-Pass Construction

`build_coaching_tree()` implements the two-phase detect-then-verify
architecture described in MATH.md Section 3.3 and 6.4:

1. **Phase 1 (screen)**: MultiPV analysis at the decision point generates
   candidate continuations. `_rank_nodes_by_teachability()` scores each
   candidate by walking the continuation chain and counting new motif types
   per ply.

2. **Phase 2 (validate)**: Top-ranked candidates receive deeper Stockfish
   analysis, replacing shallow continuations with deep PVs.

This matches the ChessGrammar pipeline cited in MATH.md: Phase 1 performs fast
geometric/heuristic detection; Phase 2 performs deeper verification.

### 6.3 Soundness Degree

The graded soundness sigma_d from MATH.md Section 6.5 approximates to the
Stockfish centipawn evaluation at each node. A tactic in a line where Stockfish
confirms a growing advantage has high soundness; a tactic where the evaluation
hovers near zero is marginal. The code uses centipawn scores -- not an explicit
sigma_d metric -- for ranking alternatives, classifying moves as
good/inaccuracy/mistake/blunder, and detecting whether an advantage
materializes through a continuation.

---

## 7. Motif Rendering and Report Generation

These modules have no direct counterpart in MATH.md but operationalize its
concepts for coaching.

### 7.1 Declarative Motif Registry

`MOTIF_REGISTRY` in `motifs.py` maps each motif type to a `MotifSpec`
containing identity extraction (`key_fn`), natural-language rendering
(`render_fn`), geometric deduplication keys, priority ordering, and item caps.
A single declaration per motif type drives four operations: identity keying,
diffing, rendering, and deduplication.

### 7.2 Ray Deduplication

When multiple motif types share a geometric ray (e.g., a pin and an x-ray on
the same diagonal), `_dedup_ray_motifs()` retains only the highest-priority
classification. Priority: absolute pin > relative pin > skewer > x-ray >
discovered attack.

### 7.3 Report Serialization

`serialize_report()` in `report.py` walks the `GameTree` outward from the
decision point: the student's played move and each alternative, with their
continuation chains. Each node's position receives a three-bucket description
via `describe_position()` (threats, opportunities, observations), and tactic
diffs describe changes between nodes. The report includes the student's move,
alternatives, continuations, material results, and warnings.

---

## 8. Complexity

The code achieves the complexity bounds described in MATH.md Section 8.1:

| Motif class | Complexity | Implementation |
|------------|-----------|----------------|
| Hanging piece | O(n) | Per-piece check via Lichess utilities |
| Ray motifs (pin, skewer, x-ray, discovered) | O(s * 8) | Single-pass `_find_ray_motifs()` over sliders |
| Fork | O(n * d) | Per-piece attack set intersection |
| Overloaded piece | O(n * d) | Per-piece duty check; `_is_sole_defender()` is O(1) via bitwise AND |

The unified ray walker is the key optimization: it detects all ray-based motifs
in one pass per slider per direction, replacing separate passes for pins,
skewers, x-rays, and discovered attacks.

---

## What Remains in MATH.md Only

The following concepts from MATH.md are formalized but not implemented:

- **Explicit graph materialization** (Section 2.1): The CPDG is computed
  implicitly, not stored as a graph object with nodes and edges.
- **Hypergraph / simplicial complex view** (Section 2.2): Tactic edges are
  dataclasses, not hyperedges in a formal hypergraph.
- **Tactic interaction graph I(P)** (Section 4.2): Compound tactics sharing
  pieces are not tracked; no overlap graph is built.
- **Minimality and tactical cores** (Section 5): No subgraph minimization or
  core extraction is performed.
- **Forcing sequence search** (Section 6.2): Soundness is approximated by
  Stockfish evaluation, not verified by explicit AND/OR tree search.
- **Proof-number search** (Section 6.2): Not implemented; Stockfish depth
  serves as the verification oracle.
- **Monotonicity and color symmetry properties** (Section 7): Theoretical
  properties, not tested or exploited.
- **Fragility metric** (Section 7.3): Betweenness centrality is not computed.
- **All open questions** (Section 10): Empirical distribution studies,
  category-theoretic formulations, spectral analysis, dynamic CPDG sequences.
