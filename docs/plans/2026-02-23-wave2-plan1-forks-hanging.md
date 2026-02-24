# Wave 2 Plan 1: Fork Detection + Hanging Piece Retreat

> **For Claude:** Execute this plan using subagent-driven-development (same session) or executing-plans (separate session / teammate).

**Goal:** Fix fork detection (defense-aware, check/royal labels) and hanging piece retreat for pinned pieces.

**Architecture:** Both fixes are internal to `src/server/analysis.py`. No new files, no API changes. Fork dataclass gets two new fields with defaults (backwards compatible). Hanging fix simplifies existing code.

**Tech Stack:** Python, python-chess, pytest

**Acceptance Criteria — what must be TRUE when this plan is done:**
- [ ] `_find_forks` collects all attacked enemy pieces (no `target_val >= piece_val` filter)
- [ ] Fork detection is defense-aware: filters out forks where capturing the undefended forker resolves all threats
- [ ] King is a valid forker (king can't be captured → fork always forces concession)
- [ ] `Fork` dataclass has `is_check_fork: bool = False` and `is_royal_fork: bool = False` fields
- [ ] Check fork = one target is the king; royal fork = targets include king AND queen
- [ ] `_find_hanging` uses a single `any(m.from_square == sq for m in board.legal_moves)` check for `can_retreat`
- [ ] Pinned pieces that can move along the pin line correctly show `can_retreat=True`
- [ ] All existing tests pass
- [ ] New tests cover each fix

**Dependencies:** Wave 1 complete (get_piece_value already landed)

---

### Task 1: Defense-aware fork detection with check/royal labels [Independent]

**Context:** The chess analysis module at `src/server/analysis.py` has a `_find_forks` function (lines 755-783) that detects tactical forks. It has a bug: the value filter `target_val >= piece_val` (line 772) misses forks where the forking piece is worth more than the targets. For example, a defended queen forking two undefended rooks is a real fork but gets filtered out because rook(5) < queen(9).

A fork is a tactic where a single piece attacks 2+ enemy pieces such that the opponent cannot adequately address all threats. The key insight: a fork forces a concession if (a) one target is the king (must address check), (b) the forker is defended (capturing it loses material), or (c) the forker is worth less than the most valuable target. King forks are valid tactics (especially in endgames) because the king can never be captured.

The `Fork` dataclass (line ~470) needs two new boolean fields: `is_check_fork` (one target is the king) and `is_royal_fork` (targets include both king and queen).

**Files:**
- Modify: `src/server/analysis.py` — Fork dataclass (~line 470) and `_find_forks` (lines 755-783)
- Modify: `tests/test_analysis.py` — add fork tests

**Depends on:** Independent

**Step 1: Add fields to Fork dataclass**

Find the `Fork` dataclass in `src/server/analysis.py` (around line 470). It currently looks like:

```python
@dataclass
class Fork:
    forking_square: str
    forking_piece: str
    targets: list[str]
    target_pieces: list[str]
    color: str = ""
```

Add two fields after `color`:

```python
    is_check_fork: bool = False   # one target is the king
    is_royal_fork: bool = False   # targets include both king and queen
```

**Step 2: Write failing tests**

Add these tests to `tests/test_analysis.py`. First verify the FEN geometry using `python3 -c "import chess; b = chess.Board('FEN'); print(b)"` and adjust if needed.

```python
def test_fork_knight_forks_rook_and_bishop():
    """Classic knight fork of two valuable pieces."""
    # Nd5 attacks Rb6 (via b6) and Bf4 (via f4)
    board = chess.Board("4k3/8/1r6/3N4/5b2/8/8/4K3 w - - 0 1")
    tactics = analyze_tactics(board)
    forks = [f for f in tactics.forks if f.forking_square == "d5"]
    assert len(forks) == 1
    assert "b6" in forks[0].targets
    assert "f4" in forks[0].targets

def test_fork_check_fork_labeled():
    """Knight fork including king = check fork."""
    # Nf7 attacks Kd8 and Rh8
    board = chess.Board("3k3r/5N2/8/8/8/8/8/4K3 b - - 0 1")
    tactics = analyze_tactics(board)
    forks = [f for f in tactics.forks if f.forking_square == "f7"]
    assert len(forks) == 1
    assert forks[0].is_check_fork is True
    assert forks[0].is_royal_fork is False

def test_fork_royal_fork_labeled():
    """Knight fork of king and queen = royal fork (also a check fork)."""
    # Nc7 attacks Ke8 and Qa6
    board = chess.Board("4k3/2N5/q7/8/8/8/8/4K3 b - - 0 1")
    tactics = analyze_tactics(board)
    forks = [f for f in tactics.forks if f.forking_square == "c7"]
    assert len(forks) == 1
    assert forks[0].is_royal_fork is True
    assert forks[0].is_check_fork is True

def test_fork_king_can_fork_in_endgame():
    """King attacking two enemy rooks = valid fork (king can't be captured)."""
    # Kd5 attacks Rc4 and Re4
    board = chess.Board("8/8/8/3K4/2r1r3/8/8/7k w - - 0 1")
    tactics = analyze_tactics(board)
    king_forks = [f for f in tactics.forks
                  if f.forking_square == "d5" and f.forking_piece == "K"]
    assert len(king_forks) == 1

def test_fork_not_detected_when_forker_undefended_and_worth_more():
    """Undefended queen 'forking' two knights — capturing queen solves everything."""
    # Qd5 undefended, attacks two black knights. Capturing Qd5 is a huge win.
    # This is NOT a real fork because the opponent can just take the queen.
    board = chess.Board("4k3/8/1n6/3Q4/5n2/8/8/4K3 w - - 0 1")
    tactics = analyze_tactics(board)
    # Verify Qd5 attacks both knights
    # Queen(9) undefended, targets are knights(3). Not defended, not check,
    # forker_val(9) > max_target_val(3). All three conditions fail → not a fork.
    queen_forks = [f for f in tactics.forks
                   if f.forking_square == "d5" and f.forking_piece == "Q"]
    assert len(queen_forks) == 0
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_analysis.py -k "test_fork" -v`
Expected: Some tests FAIL (new behavior not implemented yet, old filter wrong)

**Step 4: Implement defense-aware `_find_forks`**

Replace the `_find_forks` function (lines 755-783) with:

```python
def _find_forks(board: chess.Board) -> list[Fork]:
    forks = []
    for color in (chess.WHITE, chess.BLACK):
        color_name = _color_name(color)
        enemy = not color
        for sq in chess.SquareSet(board.occupied_co[color]):
            piece = board.piece_at(sq)
            if piece is None:
                continue

            attacks = board.attacks(sq)
            targets = []
            target_pieces = []
            target_types = []
            for target_sq in attacks:
                target_piece = board.piece_at(target_sq)
                if target_piece and target_piece.color == enemy:
                    targets.append(chess.square_name(target_sq))
                    target_pieces.append(target_piece.symbol())
                    target_types.append(target_piece.piece_type)

            if len(targets) < 2:
                continue

            # Defense-awareness: a fork forces a concession only if capturing the
            # forker doesn't resolve all threats. Heuristic:
            #   (a) check fork — must address check, concedes other target
            #   (b) forker is defended — capturing it costs material
            #   (c) forker is worth less than max target — ignoring fork loses more
            # King as forker: can't be captured, always forces concession.
            has_king_target = chess.KING in target_types
            forker_defended = (
                piece.piece_type == chess.KING
                or bool(board.attackers(color, sq))
            )
            forker_val = get_piece_value(piece.piece_type, king=1000)
            max_target_val = max(
                get_piece_value(tt, king=1000) for tt in target_types
            )

            is_real_fork = (
                has_king_target
                or forker_defended
                or forker_val < max_target_val
            )
            if not is_real_fork:
                continue

            has_queen_target = chess.QUEEN in target_types

            forks.append(Fork(
                forking_square=chess.square_name(sq),
                forking_piece=piece.symbol(),
                targets=targets,
                target_pieces=target_pieces,
                color=color_name,
                is_check_fork=has_king_target,
                is_royal_fork=has_king_target and has_queen_target,
            ))
    return forks
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_analysis.py -k "test_fork" -v`
Expected: All new fork tests PASS.

Then run full suite: `uv run pytest tests/ -v`
Expected: PASS. Some existing fork tests may need updating if they relied on the old (buggy) value filter. Check each failure — if it was testing old incorrect behavior, update the assertion.

**Step 6: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: defense-aware fork detection with check/royal fork labels

Removes wrong target_val >= piece_val filter. Forks verified to force a
concession via heuristic: check fork, forker defended, or forker worth
less than target. King valid as forker. New is_check_fork and
is_royal_fork fields on Fork dataclass."
```

---

### Task 2: Fix hanging piece retreat for pinned pieces [Independent]

**Context:** The chess analysis module at `src/server/analysis.py` has a `_find_hanging` function (lines 786-818) that detects hanging (undefended attacked) pieces and reports whether they `can_retreat`. It currently has three branches:

```python
if board.is_pinned(color, sq):
    can_retreat = False          # BUG: too strict
elif piece.piece_type == chess.PAWN:
    can_retreat = any(m.from_square == sq for m in board.legal_moves)
else:
    can_retreat = not _lichess_is_trapped(board, sq)
```

The pinned branch is wrong — setting `can_retreat=False` for all pinned pieces ignores that pinned pieces CAN move along the pin line. For example, a rook pinned along a file can still move up or down that file. `board.legal_moves` in python-chess already encodes pin restrictions correctly — it only generates moves along the pin line for pinned pieces.

The fix: collapse all three branches into `any(m.from_square == sq for m in board.legal_moves)`. This handles pinned pieces (restricted to pin line), pawns, and regular pieces uniformly. The `is_trapped` import is no longer needed in this function.

**Files:**
- Modify: `src/server/analysis.py` (lines 786-818 `_find_hanging`)
- Modify: `tests/test_analysis.py` (add hanging tests)

**Depends on:** Independent

**Step 1: Write failing tests**

Add these tests to `tests/test_analysis.py`:

```python
def test_hanging_pinned_piece_can_retreat_along_pin_line():
    """A rook pinned along a file can still retreat along that file."""
    # Qe8 pins Re4 to Ke1. Re4 can move along e-file (e2, e3, e5, e6, e7, e8).
    # Nf2 attacks Re4, making it hanging.
    board = chess.Board("4q3/8/8/8/4R3/8/5n2/4K3 w - - 0 1")
    # Verify setup: Re4 is pinned, has legal moves, and is attacked
    assert board.is_pinned(chess.WHITE, chess.E4)
    tactics = analyze_tactics(board)
    hanging_rook = [h for h in tactics.hanging if h.square == "e4"]
    # Re4 has legal moves along the e-file → can_retreat should be True
    if hanging_rook:
        assert hanging_rook[0].can_retreat is True

def test_hanging_unpinned_piece_with_escape():
    """Normal (unpinned) hanging piece with escape squares has can_retreat=True."""
    # Nb5 attacked by Pa6, but knight can move to c3, d4, etc.
    board = chess.Board("4k3/8/p7/1N6/8/8/8/4K3 w - - 0 1")
    tactics = analyze_tactics(board)
    hanging_knight = [h for h in tactics.hanging if h.square == "b5"]
    if hanging_knight:
        assert hanging_knight[0].can_retreat is True
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analysis.py -k "test_hanging" -v`
Expected: `test_hanging_pinned_piece_can_retreat_along_pin_line` FAILS (current code returns `can_retreat=False` for pinned pieces)

**Step 3: Simplify `_find_hanging`**

Replace lines 786-818 with:

```python
def _find_hanging(board: chess.Board) -> list[HangingPiece]:
    """Find hanging pieces using x-ray-aware defense detection from Lichess."""
    from server.lichess_tactics import is_hanging as _lichess_is_hanging

    hanging = []
    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        for sq in chess.SquareSet(board.occupied_co[color]):
            piece = board.piece_at(sq)
            if piece is None or piece.piece_type == chess.KING:
                continue
            attackers = board.attackers(enemy, sq)
            if attackers and _lichess_is_hanging(board, piece, sq):
                if color == board.turn:
                    # Owner moves next — check if piece has any legal move.
                    # board.legal_moves handles pin restrictions: a pinned piece
                    # can only move along the pin line, which is correct.
                    can_retreat = any(m.from_square == sq for m in board.legal_moves)
                else:
                    # Opponent moves next — can capture immediately
                    can_retreat = False
                hanging.append(HangingPiece(
                    square=chess.square_name(sq),
                    piece=piece.symbol(),
                    attacker_squares=[chess.square_name(a) for a in attackers],
                    color=_color_name(color),
                    can_retreat=can_retreat,
                ))
    return hanging
```

Key changes:
- Removed the `is_pinned` branch (was always `can_retreat=False` — wrong)
- Removed the `is_trapped` branch and its import
- Single `board.legal_moves` check handles all cases: pinned pieces (moves along pin line), pawns, and regular pieces
- `_lichess_is_trapped` import removed from this function (still used in `_find_trapped_pieces`)

**Step 4: Run tests**

Run: `uv run pytest tests/test_analysis.py -k "test_hanging" -v`
Expected: All PASS.

Then full suite: `uv run pytest tests/ -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: pinned pieces can retreat along pin line in hanging detection

Replaced three-branch logic (pinned/pawn/other) with unified
board.legal_moves check. Pinned pieces now correctly show can_retreat=True
when they have legal moves along the pin line."
```
