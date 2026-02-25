# Tactic Valuation and Teachability Scoring

A hanging queen matters more than an x-ray attack. A mate-in-2 trumps a 0.3-pawn advantage. Chess Teacher quantifies these differences with **Static Exchange Evaluation (SEE)** for material calculation and **teachability scoring** for pedagogical prioritization.

---

## Static Exchange Evaluation (SEE)

**SEE** calculates the material outcome of a capture sequence, assuming both sides play optimally on a single square. It answers: *"If I capture here, and they recapture, and I recapture again... what's the final material balance?"*

### Why SEE?

LLMs hallucinate chess analysis. They confidently claim "you can win the queen" when the queen is defended. Stockfish provides ground-truth evaluation, but it doesn't explain *why* a tactic is valuable — only that the resulting position is better.

SEE bridges this gap. It provides:
- **Concrete material values**: "Winning this exchange gains 3.0 pawns" vs. "Winning this exchange gains 0.1 pawns"
- **Pin-aware defense**: A pinned defender cannot recapture — SEE accounts for this
- **Forcing sequence logic**: If both sides play optimally, what do we actually win?

SEE is not perfect — it ignores positional factors, tempo, and non-local tactics — but it's correct enough to prevent the LLM from making false claims about material.

### Algorithm

SEE simulates a capture chain with least-valuable-piece-first (LVP) ordering:

1. **Attacker captures** the target with their least valuable piece
2. **Defender recaptures** with *their* least valuable piece
3. Repeat until one side chooses to **stand pat** (stop capturing)
4. **Back-propagate** stand-pat logic to find the true SEE value

The algorithm uses a **simulated board** to detect x-ray attackers that become revealed when pieces are removed from the capture chain.

### Key details

**Pin awareness:** `_can_capture_on()` checks whether a defender is pinned off the target ray. Pinned defenders cannot recapture; SEE excludes them.

**X-ray discovery:** The algorithm copies the board and removes pieces during simulation. When a piece leaves the capture chain, hidden attackers (rooks behind pawns, bishops behind knights) join it.

**Piece values:** P=100, N=300, B=300, R=500, Q=900, K=10000 (centipawns).

**Defense notes:** When a piece is "defended" by a pinned piece, SEE excludes that defender and records why in `defense_notes` (e.g., "defender knight on e4 pinned to king"). Tactical chains use these notes to link pins to their consequences.

---

## Tactic-Specific Valuation

Each motif type has custom valuation logic. The system dispatches on motif type:

### Hanging Pieces
**Valuation:** SEE from opponent's perspective.
**Sound if:** SEE > 0 (opponent wins material by capturing).

### Pins
- **Absolute pin:** Pinned piece is immobilized. Value = pinned piece value.
- **Relative pin:** Pinned piece can move but loses the pinned-to piece. Value = SEE of capturing the pinned piece.

### Forks
**Valuation:** Opponent saves their most valuable target; we capture the second-most valuable.
**Check forks:** King must move; we capture the highest non-king target.
**Adjustment:** If opponent can profitably capture the forking piece, reduce the fork value.

### Skewers
**Valuation:**
- **Absolute skewer (king in front):** King must move; behind piece is lost. Value = behind piece.
- **Relative skewer:** Front piece should move; behind piece exposed. Value = SEE on behind piece.

### Discovered Attacks
**Valuation:** SEE on the discovered attack target.
**Caveat:** Ignores the blocker's move value (positional only).

### Capturable Defenders
**Valuation:** Two-step calculation:
1. **Step 1:** SEE of capturing the defender
2. **Step 2:** If profitable (SEE ≥ 0), add the value of the now-undefended charge piece

### Overloaded Pieces
**Valuation:** Heuristic — the minimum value among the defended squares (opponent exploits the weakest duty).
**Note:** Marked as `source="heuristic"` in `TacticValue` to signal approximation.

---

## TacticValue Dataclass

All valuation functions return a `TacticValue`:

```python
@dataclass
class TacticValue:
    material_delta: int              # centipawns: positive = tactic wins material
    is_sound: bool                   # True if material_delta > 0 (or forced for abs pins/skewers)
    defense_notes: str = ""          # Why defenders can't defend (pin info, etc.)
    source: str = "see"              # "see" or "heuristic"
```

**Fields:**
- `material_delta`: Estimated material gain in centipawns
- `is_sound`: Whether the tactic actually wins material (filters unsound sacrifices)
- `defense_notes`: Human-readable explanation of why the tactic works (used in tactical chains)
- `source`: Valuation methodology (`"see"` for SEE-based, `"heuristic"` for approximations)

---

## Teachability Scoring

SEE provides **material accuracy**. Teachability scoring provides **pedagogical priority**.

A line with a hanging queen (9.0 pawns) is obviously more important than a line with an overloaded knight (0.5 pawns). But teachability also accounts for:
- **Mate threats**: Worth more than material
- **Checkmate**: Highest priority
- **Sacrifices**: Pedagogically interesting even if unsound
- **Positional motifs**: Weak pawns, centralization, etc.
- **Deep-only alternatives**: Interesting ideas buried 5 plies deep (lower priority)
- **Eval loss**: Alternatives worse than the student's move (negative weight)

### TeachabilityWeights

The scoring system is configurable via `TeachabilityWeights`:

```python
@dataclass
class TeachabilityWeights:
    motif_base: dict[str, float]     # base score per motif type
    value_bonus_per_100cp: float     # bonus per 100cp of material
    mate_bonus: float                # bonus for mate threats
    checkmate_bonus: float           # bonus for checkmate
    sacrifice_bonus: float           # bonus for sound sacrifices
    positional_bonus: float          # bonus for positional motifs (weak pawns, etc.)
    deep_only_penalty: float         # penalty for alternatives only on deep lines
    eval_loss_penalty: float         # penalty for eval-losing alternatives
    unsound_penalty: float           # penalty for unsound tactics (currently 0)
```

**Defaults:**
```python
DEFAULT_WEIGHTS = TeachabilityWeights(
    motif_base={
        "pin": 3.0,
        "fork": 3.0,
        "skewer": 3.0,
        "hanging": 3.0,
        "discovered": 3.0,
        "double_check": 3.0,
        "trapped": 3.0,
        "mate_threat": 3.0,
        "back_rank": 2.0,
        "xray": 2.0,
        "exposed_king": 2.0,
        "overloaded": 2.0,
        "capturable_defender": 2.0,
    },
    value_bonus_per_100cp=1.0,
    mate_bonus=5.0,
    checkmate_bonus=100.0,
    sacrifice_bonus=4.0,
    positional_bonus=1.0,
    deep_only_penalty=-2.0,
    eval_loss_penalty=-3.0,
    unsound_penalty=0.0,
)
```

### Scoring Algorithm

For each alternative line (engine-suggested move):

1. **Start with motif base scores:** Sum `motif_base[motif_type]` for each detected motif
2. **Add value bonuses:**
   - For each valued motif (pins, forks, hanging, etc.), add `value_bonus_per_100cp * (material_delta / 100)`
   - High-value motifs (double-check, trapped) get a flat bonus
   - Moderate-value motifs (xray, exposed king, overloaded, capturable defender) get a smaller flat bonus
3. **Add special bonuses:**
   - Mate threat: `+mate_bonus`
   - Checkmate: `+checkmate_bonus`
   - Sound sacrifice: `+sacrifice_bonus`
   - Positional motifs: `+positional_bonus` per motif
4. **Apply penalties:**
   - Deep-only line (no tactics on main line): `+deep_only_penalty`
   - Eval loss (alternative worse than student's move): `+eval_loss_penalty`

`rank_by_teachability()` in `game_tree.py` scores **entire continuations**, not just the first move. A line with a deep tactic (visible only after 3 moves) scores higher than a line with no tactics at all.

---

## Value-Aware Motif Rendering

Not all detected motifs need to be shown to the student. A 0.1-pawn x-ray is technically a tactic, but teaching it adds noise.

### Rendering Thresholds

The renderer filters motifs by value tier:

**Thresholds:**
- **High-value motifs** (double-check, trapped): Always rendered
- **Moderate-value motifs** (xray, exposed king, overloaded, capturable defender): Always rendered (these are complex tactics worth explaining even if low-value)
- **Valued motifs** (pins, forks, hanging, etc.): Rendered if `material_delta >= 50cp` (configurable)

This prevents spam like:
- "Your rook has an x-ray on their pawn through their knight (worth 0.1 pawns)"
- "Your bishop is pinning their knight to their rook (but they can break the pin profitably)"

Instead, the coach focuses on **meaningful tactics** — those that actually affect the evaluation or create forcing sequences.

### Configuration

Rendering thresholds are configured in `motifs.py`:

```python
RENDER_THRESHOLD_CP = 50  # minimum material delta to render a valued motif
```

Adjust this value to control verbosity:
- **Lower threshold (20cp)**: More motifs shown (useful for beginners learning pattern recognition)
- **Higher threshold (100cp)**: Fewer motifs shown (useful for advanced players focusing on critical tactics)

---

## Use Cases

### 1. Filtering Alternatives in Coaching Reports

When the engine suggests 5 alternatives, SEE and teachability scoring select the **2 most pedagogically valuable** to show the student.

**Example:**
```
Alternative 1: Nxe5 (fork on d7 and f7, winning rook — 5.0 pawns)
Alternative 2: Bxf7+ (discovered attack on queen after king moves — 9.0 pawns)
[3 other alternatives suppressed — lower teachability scores]
```

### 2. Preventing False Positives

The pin detector finds all pins, including profitably breakable ones. SEE filters unsound pins: if `_value_pin()` returns `is_sound=False`, the renderer skips them.

### 3. Tactical Chain Value Annotations

When a pin creates a hanging piece, the system shows the **total value** of the chain:

```
Your knight on d4 is pinned to your king by their bishop on a1.
(This pin leaves your pawn on f5 hanging — worth ~1.0 pawns.)
```

The `~1.0 pawns` comes from SEE valuation of the hanging pawn.

### 4. Prioritizing Mate Threats

Mate threats receive a large `mate_bonus` in teachability scoring. A line with mate-in-3 ranks above a line winning 5 pawns, because **forcing checkmate** is the ultimate teaching moment.

---

## Testing

Tests:
- `tests/test_see.py` — SEE correctness, pin awareness, x-ray discovery
- `tests/test_game_tree.py` — teachability scoring with configurable weights
- `tests/test_motifs.py` — rendering thresholds, value-aware filtering

Run:
```bash
pytest tests/test_see.py tests/test_game_tree.py -v
```

---

## Performance

### SEE Cost

SEE is **cheap** compared to full engine analysis. Each SEE call:
- Copies the board once (O(1) in python-chess)
- Builds attacker lists for both sides (O(attackers))
- Simulates capture chain (typically 2-4 captures)

SEE runs in **microseconds** per call. The system calls SEE for every detected motif (10-30 per position), adding ~1ms total overhead.

### Teachability Scoring Cost

Teachability scoring is a **single DFS walk** over the game tree, computing scores at each node. Cost is O(nodes), typically < 50 nodes per coaching interaction.

### Rendering Cost

Value-aware filtering **reduces** LLM token count. By suppressing low-value motifs, the coaching prompt is shorter, which:
- Reduces LLM latency
- Improves coaching focus (less noise)
- Decreases API cost

---

## Future Work

### Dynamic Thresholds

Current thresholds (50cp for rendering, motif base scores) are static. Future work:
- **Elo-adaptive thresholds**: Beginners see more motifs (lower threshold), advanced players see fewer
- **Position-adaptive thresholds**: In quiet positions, show more motifs; in sharp positions, focus on forcing lines

### Positional SEE

Current SEE is **material-only**. It ignores:
- Tempo (gaining time)
- Piece activity (knight on the rim vs. knight centralized)
- Pawn structure (doubled pawns, passed pawns)

A **positional SEE** would adjust material deltas by positional factors, e.g.:
- Winning a bishop pair: +50cp bonus
- Doubling opponent's pawns: +30cp bonus
- Centralizing a piece: +20cp bonus

### Multi-Square SEE

Current SEE evaluates **one target square**. Some tactics (forks, discovered attacks) involve multiple squares. A **multi-square SEE** would calculate the combined value of a fork sequence:
1. Fork targets A and B
2. Opponent saves A
3. We capture B
4. Net value = SEE(B) - cost_of_forking_piece

This is partially implemented in `_value_fork()` but could be generalized.

---

## References

- **Implementation**:
  - `src/server/analysis/tactics/see.py` (SEE algorithm)
  - `src/server/analysis/tactics/valuation.py` (tactic-specific valuation)
  - `src/server/game_tree.py` (teachability scoring)
  - `src/server/motifs.py` (rendering thresholds)
- **Tests**:
  - `tests/test_see.py` (SEE correctness)
  - `tests/test_game_tree.py` (teachability scoring)
  - `tests/test_motifs.py` (value-aware rendering)
- **Commits**:
  - SEE implementation: `2c61c33` ("feat: add Static Exchange Evaluation and tactic valuation (Phase 1)")
  - Teachability scoring: `56fddc8` ("feat: value-aware teachability ranking with TeachabilityWeights")
  - Value-aware rendering: `a62bca2` ("feat: value-aware motif rendering with tunable config and threshold filtering")
- **Theory**: [DESIGN-THEORY.md](DESIGN-THEORY.md) (position analysis formalism)
