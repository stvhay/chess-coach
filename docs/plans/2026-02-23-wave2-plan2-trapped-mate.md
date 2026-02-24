# Wave 2 Plan 2: Trapped Pieces + Mate Patterns

> **For Claude:** Execute this plan using subagent-driven-development (same session) or executing-plans (separate session / teammate).

**Goal:** Fix trapped piece detection to check both sides (not just side to move) and fix mate pattern detection to check all patterns (not stop at first match).

**Architecture:** Both fixes are internal to `src/server/analysis.py`. No new files, no API changes. Trapped fix uses the null move pattern (`board.push(chess.Move.null())` / `board.pop()`) to flip the turn temporarily. Mate pattern fix changes `elif` to `if`.

**Tech Stack:** Python, python-chess, pytest

**Acceptance Criteria — what must be TRUE when this plan is done:**
- [ ] `_find_trapped_pieces` checks both colors, not just `board.turn`
- [ ] Null move pattern used for non-moving side (push/pop, no board copy)
- [ ] Null-move-into-check positions are guarded (skip that side)
- [ ] `_find_mate_patterns` uses `if` (not `elif`) for each pattern detector
- [ ] `boden_or_double_bishop_mate` always runs (not gated behind `else`)
- [ ] All existing tests pass
- [ ] New tests cover each fix

**Dependencies:** Wave 1 complete. Independent of Wave 2 Plan 1.

---

### Task 1: Fix trapped piece detection for both sides [Independent]

**Context:** The chess analysis module at `src/server/analysis.py` has a `_find_trapped_pieces` function (lines 833-849) that detects pieces with no safe escape using `is_trapped` from the vendored Lichess tactics library. The bug: it only checks pieces of `board.turn` (the side to move) because `is_trapped` internally calls `board.legal_moves`, which only generates moves for the side to move.

```python
def _find_trapped_pieces(board: chess.Board) -> list[TrappedPiece]:
    from server.lichess_tactics import is_trapped as _lichess_is_trapped
    trapped = []
    for sq in chess.SquareSet(board.occupied_co[board.turn]):  # BUG: only one side
        piece = board.piece_at(sq)
        if piece is None:
            continue
        if _lichess_is_trapped(board, sq):
            trapped.append(TrappedPiece(
                square=chess.square_name(sq),
                piece=piece.symbol(),
                color=_color_name(board.turn),
            ))
    return trapped
```

To check the other side, use the null move pattern: `board.push(chess.Move.null())` flips the turn, then `board.pop()` restores it. This is the standard python-chess approach for temporarily changing the side to move. Push/pop are paired — no mutation leaks.

Guard against null-move-into-check: if the side we flipped to is in check (which can happen in positions where the opponent just gave check), `board.legal_moves` would be unreliable. Skip that side.

The `TrappedPiece` dataclass (around line 486) already has a `color` field:
```python
@dataclass
class TrappedPiece:
    square: str
    piece: str
    color: str = ""
```

The `is_trapped` function (from `server.lichess_tactics._util`) checks: (1) `is_in_bad_spot` — piece is attacked by lower-value piece or undefended, (2) all legal moves from that square lead to squares that are also `is_in_bad_spot`. It excludes pawns and kings. It requires the piece to be the side to move.

**Files:**
- Modify: `src/server/analysis.py` (lines 833-849 `_find_trapped_pieces`)
- Modify: `tests/test_analysis.py` (add trapped tests)

**Depends on:** Independent

**Step 1: Write tests**

Add to `tests/test_analysis.py`. The test verifies the structural fix (both sides checked) even if constructing a position where `is_trapped` returns True for the non-moving side is difficult. The key test is that the function iterates both colors.

```python
def test_trapped_pieces_checks_both_sides():
    """Function should check both colors, not just board.turn."""
    # We verify structurally: with same position, flipping the turn
    # should detect trapped pieces for the other side.
    # Use a position where we know is_trapped behavior.
    # Even if is_trapped returns False for all pieces, the function
    # should at least iterate both sides' pieces.
    board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    tactics = analyze_tactics(board)
    # No pieces to trap — just verify no crash
    assert tactics.trapped_pieces == []

def test_trapped_pieces_no_crash_on_check_position():
    """Null move into check should not crash — just skip that side."""
    # White is in check from Qe1. Null move would put Black "to move" but
    # White is in check — the guard should skip.
    board = chess.Board("4k3/8/8/8/8/8/8/3qK3 w - - 0 1")
    # White king in check from Qd1
    assert board.is_check()
    tactics = analyze_tactics(board)
    # Should not crash, even though null move from this position is weird
    assert isinstance(tactics.trapped_pieces, list)
```

The implementing agent should also try to construct a position where `is_trapped` returns True for a non-moving-side piece, to have a positive test. A good candidate: a knight on the rim attacked by a pawn, with all escape squares also attacked. Example to try:

```python
def test_trapped_detects_non_moving_side():
    """Trapped piece detected for the side NOT to move."""
    # The implementing agent should construct a position where:
    # - It's White's turn
    # - A Black piece passes is_in_bad_spot (attacked by lower value piece)
    # - All escape squares are also bad spots
    # Try various positions with the Lichess is_trapped function.
    # If no position triggers is_trapped for the non-moving side,
    # this test can verify the iteration happens (check the function
    # iterates board.occupied_co for both colors, not just board.turn).
    pass  # Implementing agent fills in after testing
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_analysis.py -k "test_trapped" -v`
Expected: Existing tests PASS, new structural tests may PASS or FAIL depending on implementation.

**Step 3: Fix `_find_trapped_pieces`**

Replace lines 833-849 with:

```python
def _find_trapped_pieces(board: chess.Board) -> list[TrappedPiece]:
    """Find pieces with no safe escape using Lichess trapped-piece detection."""
    from server.lichess_tactics import is_trapped as _lichess_is_trapped

    trapped = []
    for color in (chess.WHITE, chess.BLACK):
        # is_trapped uses board.legal_moves, which only works for side to move.
        # Use null move to flip turn for the non-moving side.
        needs_null_move = color != board.turn
        if needs_null_move:
            board.push(chess.Move.null())

        # Guard: null move into check produces no useful legal_moves
        if not board.is_check():
            for sq in chess.SquareSet(board.occupied_co[color]):
                piece = board.piece_at(sq)
                if piece is None:
                    continue
                if _lichess_is_trapped(board, sq):
                    trapped.append(TrappedPiece(
                        square=chess.square_name(sq),
                        piece=piece.symbol(),
                        color=_color_name(color),
                    ))

        if needs_null_move:
            board.pop()

    return trapped
```

Key changes:
- Loop over both `chess.WHITE` and `chess.BLACK` instead of just `board.turn`
- Use `board.push(chess.Move.null())` / `board.pop()` to flip turn temporarily
- Guard: skip if `board.is_check()` after null move (position would be invalid)
- Each trapped piece gets the correct `color` label

**Step 4: Run all tests**

Run: `uv run pytest tests/test_analysis.py -k "test_trapped" -v`
Expected: PASS.

Then full suite: `uv run pytest tests/ -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: detect trapped pieces for both sides, not just side to move

Uses null move pattern (push/pop) to check the non-moving side's pieces.
Guards against null-move-into-check positions."
```

---

### Task 2: Fix mate pattern detection — check all patterns [Independent]

**Context:** The chess analysis module at `src/server/analysis.py` has a `_find_mate_patterns` function (lines 852-887) that detects named checkmate patterns (back rank, smothered, arabian, hook, anastasia, dovetail, boden, double bishop) using detector functions from the vendored Lichess tactics library.

The bug: it uses an `elif` chain that stops after the first match:

```python
if back_rank_mate(board):
    patterns.append(MatePattern(pattern="back_rank"))
elif smothered_mate(board):          # skipped if back_rank matched!
    patterns.append(MatePattern(pattern="smothered"))
elif arabian_mate(board):            # skipped if either above matched!
    ...
else:
    boden_result = boden_or_double_bishop_mate(board)  # only runs if nothing above matched!
```

This means: (1) only the first matching pattern is reported, (2) `boden_or_double_bishop_mate` only runs if no other pattern matched (gated behind `else`). While most checkmate positions match exactly one pattern, the code should structurally check all of them.

The fix: change `elif` to `if` for each detector, and move `boden_or_double_bishop_mate` out of the `else` block. Boden and double_bishop remain mutually exclusive (same function returns one or the other).

The `MatePattern` dataclass (around line 493):
```python
@dataclass
class MatePattern:
    pattern: str  # e.g. "back_rank", "smothered", "arabian", "hook", etc.
```

**Files:**
- Modify: `src/server/analysis.py` (lines 852-887 `_find_mate_patterns`)
- Modify: `tests/test_analysis.py` (add mate pattern tests)

**Depends on:** Independent

**Step 1: Write tests**

Add to `tests/test_analysis.py`. Construct known checkmate positions for at least two patterns.

```python
def test_mate_pattern_back_rank_detected():
    """Back rank mate should be detected."""
    # Classic back rank: Rd8# with king trapped by own pawns
    board = chess.Board("3R2k1/5ppp/8/8/8/8/8/4K3 b - - 0 1")
    # Verify it's checkmate
    assert board.is_checkmate()
    tactics = analyze_tactics(board)
    patterns = [p.pattern for p in tactics.mate_patterns]
    assert "back_rank" in patterns

def test_mate_pattern_smothered_detected():
    """Smothered mate should be detected."""
    # Classic smothered: Nf7# with king surrounded by own pieces
    # Kg8 surrounded by Rf8, Bg7(?), and Nh6 giving mate
    # Standard smothered: Kg8, Rg7(?), Rf8, Nh7... tricky.
    # Use known position: Kg8, pawns f7/g6/h7, knight on f6 giving mate?
    # Actually: Philidor's smothered mate: Kg8, Rh8, Rf8, pawn g7, Nf7#? No...
    # Best: construct and verify with python-chess
    # Kh8, Rg8, pf7, ph7, Nf7? Nf7 doesn't give check to Kh8.
    # Standard: Kg8, Rf8, Bg7... Nf6#? Nf6 gives check (attacks g8), Kg8 can't move
    # because f8 has rook, g7 has bishop, h8 attacked by Nf6, f7...
    # Let the implementing agent construct and verify a smothered mate position.
    # The key assertion is that the pattern detector finds it.
    pass  # Implementing agent constructs verified FEN

def test_mate_pattern_boden_always_checked():
    """boden_or_double_bishop_mate runs even if another pattern matched first."""
    # This is the structural fix: in the old code, boden was gated behind else.
    # Construct a boden's mate position and verify it's detected.
    # Boden's mate: two bishops on crossing diagonals checkmate the king,
    # which is trapped by friendly pieces.
    # Classic: Kc8, Rd8/Bc7 blocking, Ba6+Be5 deliver mate? Complex.
    # Let the implementing agent construct and verify.
    pass  # Implementing agent constructs verified FEN

def test_mate_pattern_non_checkmate_returns_empty():
    """Non-checkmate position returns no patterns."""
    board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    assert not board.is_checkmate()
    tactics = analyze_tactics(board)
    assert tactics.mate_patterns == []
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_analysis.py -k "test_mate_pattern" -v`
Expected: Existing tests PASS (the elif→if change doesn't break single-match cases).

**Step 3: Fix `_find_mate_patterns`**

Replace lines 852-887 with:

```python
def _find_mate_patterns(board: chess.Board) -> list[MatePattern]:
    """Detect named checkmate patterns using Lichess pattern detectors."""
    if not board.is_checkmate():
        return []

    from server.lichess_tactics._cook import (
        arabian_mate,
        anastasia_mate,
        back_rank_mate,
        boden_or_double_bishop_mate,
        dovetail_mate,
        hook_mate,
        smothered_mate,
    )

    patterns = []
    if back_rank_mate(board):
        patterns.append(MatePattern(pattern="back_rank"))
    if smothered_mate(board):
        patterns.append(MatePattern(pattern="smothered"))
    if arabian_mate(board):
        patterns.append(MatePattern(pattern="arabian"))
    if hook_mate(board):
        patterns.append(MatePattern(pattern="hook"))
    if anastasia_mate(board):
        patterns.append(MatePattern(pattern="anastasia"))
    if dovetail_mate(board):
        patterns.append(MatePattern(pattern="dovetail"))

    boden_result = boden_or_double_bishop_mate(board)
    if boden_result == "bodenMate":
        patterns.append(MatePattern(pattern="boden"))
    elif boden_result == "doubleBishopMate":
        patterns.append(MatePattern(pattern="double_bishop"))

    return patterns
```

Key changes:
- `elif` → `if` for each pattern (all patterns checked independently)
- `boden_or_double_bishop_mate` always runs (moved out of `else` block)
- Boden/double_bishop remain mutually exclusive (`elif` kept between them since same function returns one or the other)

**Step 4: Run all tests**

Run: `uv run pytest tests/test_analysis.py -k "test_mate_pattern" -v`
Expected: PASS.

Then full suite: `uv run pytest tests/ -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: check all mate patterns instead of stopping at first match

Changed elif chain to if statements so all matching patterns are detected.
boden_or_double_bishop_mate now always checked, not gated behind else."
```
