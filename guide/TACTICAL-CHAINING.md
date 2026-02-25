# Tactical Chaining

Tactical motifs don't exist in isolation. A pin makes a piece immobile, which makes it **hanging** (undefended). An overloaded piece defends multiple squares, and when forced to move, all defended pieces become **hanging**. These cause-and-effect relationships make positions teachable — the student can see not just *what* the tactic is, but *why* it matters.

Chess Teacher detects and explains these chains in two tiers:

- **Tier 1 (pin→hanging)**: A pinned piece cannot move to defend another piece, leaving that piece hanging
- **Tier 2 (overload→hanging, capturable-defender→hanging)**: An overloaded defender protects multiple pieces; a capturable defender creates conditional hanging

---

## What Are Tactical Chains?

A **tactical chain** links a primary motif (the cause) to a secondary motif (the consequence). The primary motif creates the condition; the secondary motif is the exploitable result.

### Example: Pin Creates Hanging Piece

```
Position: White knight on d4 defends pawn on f5.
          Black bishop on a1 pins knight to White king on h8.

Chain: pin(bishop a1 → knight d4) → hanging(pawn f5)
```

The knight cannot move (pinned), so it cannot defend the pawn. The pawn is hanging because of the pin. Teaching this relationship is more valuable than teaching either motif in isolation.

### Example: Overloaded Defender

```
Position: White knight on e4 defends rook on c5 and bishop on g5.
          Black threatens both pieces.

Chain: overloaded(knight e4 defends c5, g5) → hanging(rook c5, bishop g5)
```

The knight cannot defend both pieces at once. If it moves to defend one, the other is left hanging.

### Example: Capturable Defender

```
Position: White knight on e4 defends bishop on g5.
          Black can capture the knight with check.

Chain: capturable_defender(knight e4 → bishop g5, captor: queen d5) → hanging(bishop g5)
```

The knight is not just defending the bishop — it's a **capturable** defender, meaning the opponent can remove it and immediately exploit the hanging piece.

---

## Tier 1: Pin→Hanging Chains

**Status:** Committed (Phase 1). Enabled via `CHESS_TEACHER_ENABLE_CHAINING=1`.

**Detection:** `_detect_pin_hanging_chains()` in `motifs.py` matches pins against hanging pieces by inspecting `defense_notes` computed during hanging detection. When the analyzer finds a hanging piece, it records *why* in `HangingPiece.value.defense_notes`. If that note mentions "pinned" and the square of a detected pin, the system creates a chain link.

### Rendering

Chain detection merges the pin and its consequence into one explanation:

```
Your knight on d4 is pinned to your king on h8 by their bishop on a1.
(This pin leaves your pawn on f5 hanging — worth ~1.0 pawns.)
```

The hanging piece appears inline with the pin rather than as a separate line item.

---

## Tier 2: Overload and Capturable-Defender Chains

**Status:** Committed (Phase 2). Enabled via `CHESS_TEACHER_ENABLE_TIER2_CHAINS=1` (requires `CHESS_TEACHER_ENABLE_CHAINING=1`).

**Detection:** `_detect_overload_hanging_chains()` and `_detect_capturable_defender_hanging_chains()` in `motifs.py` compare defended squares against hanging piece squares.

- **Overload→Hanging:** An overloaded piece defends multiple squares. If any defended square holds a hanging piece, a chain exists. One overloaded piece can link to multiple hanging pieces.
- **Capturable-Defender→Hanging:** A capturable defender protects another piece but can itself be captured (often with tempo). If the defended piece hangs when the defender is removed, a chain exists.

### Rendering

Tier 2 chains merge cause and consequence into one explanation:

**Overload→Hanging:**
```
Your knight on e4 is overloaded — it's defending your rook on c5 and bishop on g5, both worth ~6.0 pawns total.
```

**Capturable-Defender→Hanging:**
```
Your knight on e4 is a capturable defender (their queen on d5 can take it, leaving your bishop on g5 hanging — worth ~3.0 pawns).
```

---

## Feature Flags

Chaining is controlled by two environment variables:

### `CHESS_TEACHER_ENABLE_CHAINING`

**Default:** `0` (disabled)
**Values:** `0` or `1`

Enables **Tier 1 chain detection** (pin→hanging). When enabled:
- Pins that create hanging pieces are rendered with inline consequences
- Hanging pieces involved in chains are suppressed from standalone rendering
- No additional detection overhead (uses existing `defense_notes`)

### `CHESS_TEACHER_ENABLE_TIER2_CHAINS`

**Default:** `0` (disabled)
**Values:** `0` or `1`
**Requires:** `CHESS_TEACHER_ENABLE_CHAINING=1`

Enables **Tier 2 chain detection** (overload→hanging, capturable-defender→hanging). When enabled:
- Overloaded pieces that create hanging pieces are rendered with merged explanations
- Capturable defenders that create hanging pieces are rendered with inline consequences
- Adds square-matching passes during rendering

---

## Pedagogical Design

### Why Chains Matter

Novice players see tactics as isolated events. They notice a pin, or they notice a hanging piece, but they don't connect the two. Teaching the **relationship** between tactics builds pattern recognition and causal reasoning.

Chains answer the question: **"Why does this pin matter?"**
Answer: **"Because it makes that pawn hanging."**

This is more memorable and actionable than:
- "You have a pin here."
- "You have a hanging piece there."

### Why Two Tiers?

**Tier 1 (pin→hanging)** is the most common and most teachable chain. Pins are easy to visualize, and the consequence (immobility → loss of defense) is direct. Tier 1 has no detection cost — it reuses data already computed during hanging detection.

**Tier 2 (overload, capturable-defender)** involves more complex reasoning. Overloaded pieces require understanding that a single defender can't be in two places at once. Capturable defenders require calculating a forcing sequence (capture with tempo). These chains are less common and require additional square-matching logic, so they're opt-in.

### Why Feature Flags?

Chaining is a **pedagogical enhancement**, not a correctness fix. The system works without it. Feature flags allow:
- **Gradual rollout**: Test Tier 1 in production before enabling Tier 2
- **User preference**: Advanced players may prefer more detailed motif breakdowns; beginners may prefer consolidated chains
- **Evaluation**: Measure whether chaining improves teaching effectiveness via A/B testing
- **Debugging**: Disable chaining to isolate rendering issues

---

## Adding New Chain Types

To add a new chain type:

1. **Add detection function** in `motifs.py`:
   ```python
   def _detect_yourchain_chains(tactics: TacticalMotifs) -> dict[tuple, tuple]:
       if not is_chain_detection_enabled():
           return {}
       # Match primary motif against secondary motif
       return chains
   ```

2. **Call from `_get_chain_links()`**:
   ```python
   def _get_chain_links(tactics: TacticalMotifs) -> dict[str, dict]:
       return {
           "pin_hanging": _detect_pin_hanging_chains(tactics),
           "overload_hanging": _detect_overload_hanging_chains(tactics),
           "yourchain": _detect_yourchain_chains(tactics),  # Add here
       }
   ```

3. **Add rendering logic** in the primary motif's render function:
   ```python
   def _render_yourprimary(motif, student_is_white, is_tactic_after, chain_info):
       # Render primary motif
       text = f"Your piece on {motif.square}..."

       # Check for chain
       if key in chain_info.get("yourchain", {}):
           secondary_key = chain_info["yourchain"][key]
           text += f" (This leaves {describe_secondary(secondary_key)}.)"

       return text
   ```

4. **Update tests** in `tests/test_chaining.py`:
   ```python
   def test_yourchain_detection():
       # Arrange: position with chain
       # Act: detect chains
       # Assert: chain found
   ```

---

## Testing

Chain detection is tested in `tests/test_tier2_chains.py` and `tests/test_chaining.py`. Each test follows the pattern:

1. **Arrange**: Create a position with a known chain
2. **Act**: Analyze the position and extract chains
3. **Assert**: Verify the chain was detected and rendered correctly

Example:

```python
def test_pin_hanging_chain():
    """Pin on d4 creates hanging pawn on f5."""
    board = chess.Board("rnbqkbnr/pppppppp/8/5p2/3N4/8/PPPPPPPP/RNBQKB1R w KQkq - 0 1")
    tactics = analyze_tactics(board)
    chains = _detect_pin_hanging_chains(tactics)

    # Assert pin key is in chains
    pin_keys = [k for k in chains.keys() if k[0] == "pin"]
    assert len(pin_keys) == 1

    # Assert hanging key is the consequence
    hanging_key = chains[pin_keys[0]]
    assert hanging_key[0] == "hanging"
    assert hanging_key[1] == "f5"
```

Run chain tests:
```bash
pytest tests/test_chaining.py tests/test_tier2_chains.py -v
```

---

## Performance Considerations

### Tier 1 Cost

**Near-zero.** Tier 1 detection reuses `defense_notes` already computed during hanging detection. The matching pass is O(pins × hanging), typically < 10 comparisons per position.

### Tier 2 Cost

**Low.** Tier 2 adds square-matching passes: O(overloaded × hanging) and O(capturable-defender × hanging). In practice, positions have 0-3 overloaded pieces and 0-3 capturable defenders, so this is < 20 string comparisons per position.

Tier 2 is opt-in because the cost, though small, is nonzero.

### Rendering Cost

Chains **reduce** rendering cost by suppressing redundant motifs. Without chaining, a pin and its consequent hanging piece produce two lines. With chaining, they merge into one — fewer tokens for the LLM and more focused coaching.

---

## References

- **Implementation**: `src/server/motifs.py` (detection and rendering)
- **Tests**: `tests/test_chaining.py`, `tests/test_tier2_chains.py`
- **Commits**:
  - Tier 1: `4d03002` ("feat: annotated SEE trace + Tier 1 pin→hanging chain rendering")
  - Tier 2: `44568a2` ("feat: Tier 2 chain detection"), `0e9b748` ("feat: Tier 2 chain rendering")
- **Feature flags**: `src/server/config_flags.py`
