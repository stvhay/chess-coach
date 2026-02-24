# Wave 2 Plan 3: Back Rank Weakness + Development Counting

> **For Claude:** Execute this plan using subagent-driven-development (same session) or executing-plans (separate session / teammate).

**Goal:** Fix back rank weakness detection to use legal moves (not manual square scanning) and fix development counting to track surviving minors (not vacated home squares).

**Architecture:** Both fixes are internal to `src/server/analysis.py`. No new files, no API changes. Back rank fix uses the null move pattern for the non-moving side. Development fix changes the counting formula.

**Tech Stack:** Python, python-chess, pytest

**Acceptance Criteria — what must be TRUE when this plan is done:**
- [ ] `_find_back_rank_weaknesses` uses `board.legal_moves` to check king escape off back rank
- [ ] King moves along the back rank do NOT count as escape (only moves to a different rank)
- [ ] Null move pattern used for non-moving side
- [ ] Empty squares attacked by enemy pieces correctly detected as non-escape
- [ ] `analyze_development` counts `total_surviving_minors - minors_on_home_squares`
- [ ] Captured minor pieces do not inflate the developed count
- [ ] Promoted minor pieces count as developed (correct)
- [ ] All existing tests pass
- [ ] New tests cover each fix

**Dependencies:** Wave 1 complete. Independent of Wave 2 Plans 1 and 2.

---

### Task 1: Fix back rank weakness detection — use legal moves [Independent]

**Context:** The chess analysis module at `src/server/analysis.py` has a `_find_back_rank_weaknesses` function (lines 908-945) that detects back rank vulnerability: king on back rank with no escape, and opponent has heavy pieces. The bug: it manually checks if squares one rank forward are blocked by own pieces:

```python
for f in range(max(0, king_file - 1), min(8, king_file + 2)):
    sq = chess.square(f, forward_rank)
    piece = board.piece_at(sq)
    if piece is None or piece.color != color:
        all_blocked = False
        break
```

This misses a critical case: empty squares that are **attacked by enemy pieces**. The king can't move to an attacked square even if it's empty. Using `board.legal_moves` handles this correctly — it knows about attacks, pins, and all legality rules.

Additionally, the manual check only looks one rank forward, but king moves along the back rank (e.g., Kg1→h1) should NOT count as escape — the point of back rank weakness is that the king can't get off the rank.

The fix uses the null move pattern (`board.push(chess.Move.null())` / `board.pop()`) when checking the non-moving side, same pattern as the trapped pieces fix.

The `BackRankWeakness` dataclass (around line 504):
```python
@dataclass
class BackRankWeakness:
    weak_color: str  # "white" or "black"
    king_square: str
```

**Files:**
- Modify: `src/server/analysis.py` (lines 908-945 `_find_back_rank_weaknesses`)
- Modify: `tests/test_analysis.py` (add back rank tests)

**Depends on:** Independent

**Step 1: Write failing tests**

Add to `tests/test_analysis.py`. Verify each FEN using `uv run python3 -c "import chess; b = chess.Board('FEN'); print(b)"` before writing assertions.

```python
def test_back_rank_attacked_escape_squares():
    """Empty escape square attacked by enemy = still a back rank weakness."""
    # Kg1, pawns g2/h2. Forward escape squares: f2, g2, h2.
    # g2/h2 blocked by own pawns. f2 is empty but attacked by Bc5.
    # Bc5 attacks f2 (c5-d4-e3-f2 diagonal). Rd8 provides heavy piece threat.
    # King's only legal moves: h1 and f1 (both on back rank = not escape).
    board = chess.Board("3r4/8/8/2b5/8/8/6PP/6K1 w - - 0 1")
    tactics = analyze_tactics(board)
    br = [w for w in tactics.back_rank_weaknesses if w.weak_color == "white"]
    assert len(br) >= 1
    assert br[0].king_square == "g1"

def test_back_rank_no_weakness_with_escape():
    """King with a safe forward escape square = no back rank weakness."""
    # Kg1, pawns g2/h2. f2 is empty and NOT attacked. King can escape to f2.
    # No enemy pieces attacking f2. Rd8 provides threat but king can flee.
    board = chess.Board("3r4/8/8/8/8/8/6PP/6K1 w - - 0 1")
    tactics = analyze_tactics(board)
    br = [w for w in tactics.back_rank_weaknesses if w.weak_color == "white"]
    assert len(br) == 0

def test_back_rank_king_not_on_back_rank():
    """King not on back rank = no weakness regardless."""
    board = chess.Board("3r4/8/8/8/8/8/4K1PP/8 w - - 0 1")
    tactics = analyze_tactics(board)
    br = [w for w in tactics.back_rank_weaknesses if w.weak_color == "white"]
    assert len(br) == 0

def test_back_rank_no_heavy_pieces():
    """Back rank weakness requires opponent to have rook or queen."""
    # Kg1 trapped on back rank, but opponent has no heavy pieces.
    board = chess.Board("8/8/8/2b5/8/8/5nPP/6K1 w - - 0 1")
    tactics = analyze_tactics(board)
    br = [w for w in tactics.back_rank_weaknesses if w.weak_color == "white"]
    assert len(br) == 0
```

The implementing agent should verify each FEN produces the intended board position and king mobility. Use:
```bash
uv run python3 -c "
import chess
b = chess.Board('FEN')
print(b)
king_sq = b.king(chess.WHITE)
for m in b.legal_moves:
    if m.from_square == king_sq:
        r = chess.square_rank(m.to_square)
        print(f'  King -> {chess.square_name(m.to_square)} (rank {r}, escape: {r != 0})')
"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analysis.py -k "test_back_rank" -v`
Expected: `test_back_rank_attacked_escape_squares` FAILS (old code sees empty f2, says "not blocked", misses the weakness).

**Step 3: Fix `_find_back_rank_weaknesses`**

Replace lines 908-945 with:

```python
def _find_back_rank_weaknesses(board: chess.Board) -> list[BackRankWeakness]:
    """Detect back rank vulnerability: king on back rank with no escape,
    and opponent has a rook or queen that could threaten it."""
    weaknesses = []
    for color in (chess.WHITE, chess.BLACK):
        king_sq = board.king(color)
        if king_sq is None:
            continue
        back_rank = 0 if color == chess.WHITE else 7
        if chess.square_rank(king_sq) != back_rank:
            continue

        # Check if king has any legal move off the back rank.
        # Use null move to flip turn if this isn't the side to move.
        needs_null_move = color != board.turn
        if needs_null_move:
            board.push(chess.Move.null())

        can_escape = False
        if not board.is_check():
            for move in board.legal_moves:
                if move.from_square == king_sq and chess.square_rank(move.to_square) != back_rank:
                    can_escape = True
                    break

        if needs_null_move:
            board.pop()

        if can_escape:
            continue

        # Opponent has a rook or queen (potential back-rank attacker)
        enemy = not color
        has_heavy = (
            bool(board.pieces(chess.ROOK, enemy))
            or bool(board.pieces(chess.QUEEN, enemy))
        )
        if has_heavy:
            weaknesses.append(BackRankWeakness(
                weak_color=_color_name(color),
                king_square=chess.square_name(king_sq),
            ))
    return weaknesses
```

Key changes:
- Replaced manual escape-square loop with `board.legal_moves` iteration
- Only king moves off the back rank count as escape (`chess.square_rank(move.to_square) != back_rank`)
- King moves along the back rank (e.g., Kg1→h1) do NOT count as escape
- Uses null move pattern for the non-moving side
- Guards against null-move-into-check

**Step 4: Run all tests**

Run: `uv run pytest tests/test_analysis.py -k "test_back_rank" -v`
Expected: All PASS.

Then full suite: `uv run pytest tests/ -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: back rank weakness uses legal_moves instead of manual escape check

Correctly detects attacked escape squares as non-escape. King moves along
the back rank do not count as escape. Uses null move pattern for
non-moving side."
```

---

### Task 2: Fix development counting — track surviving minors [Independent]

**Context:** The chess analysis module at `src/server/analysis.py` has an `analyze_development` function (lines 1183-1204) that counts how many minor pieces (knights, bishops) are developed (moved off starting squares). The bug: it counts "home square vacated" instead of "piece deployed":

```python
for sq, pt in STARTING_MINORS[chess.WHITE]:
    piece = board.piece_at(sq)
    if piece is None or piece.color != chess.WHITE or piece.piece_type != pt:
        w_dev += 1
```

If a knight is captured (removed from the board), its home square is empty (`piece is None`), so the function counts it as "developed." A captured piece is not developed.

The fix: change the formula to `developed = total_surviving_minors - minors_still_on_home_squares`. This way captured pieces reduce the total count, not inflate the developed count. A promoted knight/bishop counts as a deployed minor (correct — it IS an active minor piece).

The `STARTING_MINORS` constant (around line 50):
```python
STARTING_MINORS = {
    chess.WHITE: [
        (chess.B1, chess.KNIGHT), (chess.G1, chess.KNIGHT),
        (chess.C1, chess.BISHOP), (chess.F1, chess.BISHOP),
    ],
    chess.BLACK: [
        (chess.B8, chess.KNIGHT), (chess.G8, chess.KNIGHT),
        (chess.C8, chess.BISHOP), (chess.F8, chess.BISHOP),
    ],
}
```

The `Development` dataclass (search for `class Development` in analysis.py):
```python
@dataclass
class Development:
    white_developed: int
    black_developed: int
    white_castled: bool
    black_castled: bool
```

The function also calls `analyze_king_safety` for the `castled` field — that part is unchanged.

**Files:**
- Modify: `src/server/analysis.py` (lines 1183-1204 `analyze_development`)
- Modify: `tests/test_analysis.py` (add development tests)

**Depends on:** Independent

**Step 1: Write failing tests**

Add to `tests/test_analysis.py`:

```python
def test_development_captured_piece_not_counted():
    """A captured knight should not count as developed."""
    # White's g1 knight has been captured (not on board at all).
    # b1 knight still on b1. Bc1 and Bf1 still on home squares.
    # Old code: g1 empty → counts as developed (WRONG).
    # New code: 3 surviving minors - 3 on home = 0 developed.
    board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKB1R w KQkq - 0 1")
    result = analyze_development(board)
    assert result.white_developed == 0

def test_development_moved_piece_counted():
    """A knight that moved to f3 should count as developed."""
    # Nf3 is off home square. Nb1 still home. Bc1, Bf1 still home.
    # 4 surviving minors - 3 on home = 1 developed.
    board = chess.Board("rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 1")
    result = analyze_development(board)
    assert result.white_developed == 1

def test_development_all_minors_off_home():
    """All four minor pieces moved off home squares = 4 developed."""
    # Nc3, Nf3, Bd3, Be3 — all off home. 4 surviving - 0 on home = 4.
    board = chess.Board("rnbqkbnr/pppppppp/8/8/8/2NBB3/PPPPPPPP/R2QK1NR w KQkq - 0 1")
    # Wait, this puts Nc3, Bd3, Be3, but still has Ng1? Let me fix.
    # Need all 4 white minors off home and no minors on home squares.
    board = chess.Board("r1bqk2r/pppppppp/2n1bn2/8/3BB3/2N2N2/PPPPPPPP/R2QK2R w KQkq - 0 1")
    result = analyze_development(board)
    assert result.white_developed == 4

def test_development_two_captured_one_moved():
    """Two captured minors + one moved + one home = 1 developed."""
    # White has: Nf3 (developed), Bc1 (home). Knights b1 and g1 captured. Bf1 captured.
    # 2 surviving (Nf3, Bc1) - 1 on home (Bc1) = 1 developed.
    board = chess.Board("rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/R1BQK2R w KQkq - 0 1")
    # This has Nb1 missing, Ng1 missing, Bf1 missing. Bc1 home, Nf3 developed.
    # White minors: 1 knight (f3) + 1 bishop (c1) = 2 total. 1 on home (Bc1). Developed = 1.
    result = analyze_development(board)
    assert result.white_developed == 1

def test_development_starting_position():
    """Starting position: 0 pieces developed for both sides."""
    board = chess.Board()
    result = analyze_development(board)
    assert result.white_developed == 0
    assert result.black_developed == 0
```

The implementing agent should verify each FEN using `uv run python3` to confirm the board has the intended pieces.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analysis.py -k "test_development" -v`
Expected: `test_development_captured_piece_not_counted` FAILS (old code returns 1, should return 0).

**Step 3: Fix `analyze_development`**

Replace lines 1183-1204 with:

```python
def analyze_development(board: chess.Board) -> Development:
    def _count_developed(color: chess.Color) -> int:
        """Count surviving minor pieces not on their starting squares."""
        total_minors = (
            len(board.pieces(chess.KNIGHT, color))
            + len(board.pieces(chess.BISHOP, color))
        )
        on_home = sum(
            1 for home_sq, pt in STARTING_MINORS[color]
            if (p := board.piece_at(home_sq)) is not None
            and p.color == color
            and p.piece_type == pt
        )
        return total_minors - on_home

    ks_w = analyze_king_safety(board, chess.WHITE)
    ks_b = analyze_king_safety(board, chess.BLACK)

    return Development(
        white_developed=_count_developed(chess.WHITE),
        black_developed=_count_developed(chess.BLACK),
        white_castled=ks_w.castled,
        black_castled=ks_b.castled,
    )
```

Key changes:
- Formula: `total_surviving_minors - minors_on_home_squares`
- Captured pieces reduce `total_minors`, so they don't inflate the count
- Promoted minors (e.g., pawn promotes to knight) correctly counted as active minor pieces
- `_count_developed` is a local helper, keeping the function self-contained
- Uses walrus operator (`:=`) for concise home-square check — Python 3.8+

**Step 4: Run all tests**

Run: `uv run pytest tests/test_analysis.py -k "test_development" -v`
Expected: All PASS.

Then full suite: `uv run pytest tests/ -v`
Expected: PASS. Check for any existing tests that relied on the old (buggy) counting — update assertions if they were testing incorrect behavior.

**Step 5: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: development counts surviving minors, not vacated home squares

Captured pieces no longer count as developed. Formula:
developed = total_surviving_minors - minors_on_home_squares.
Promoted minors correctly counted as active."
```
