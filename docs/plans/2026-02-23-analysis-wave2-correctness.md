# Analysis Subsystem Wave 2: Correctness Fixes — Design Document

**Goal:** Fix 6 correctness bugs in analysis.py identified during the audit. All fixes are independent — no dependencies between tasks.

**Architecture:** All changes are internal to `analysis.py`. No new files. No API changes. Dataclass shapes are unchanged (new fields have defaults). Downstream consumers (game_tree.py, descriptions.py, motifs.py, report.py) are unaffected.

**Implementation Plans (2 tasks each, all plans independent):**
- `docs/plans/2026-02-23-wave2-plan1-forks-hanging.md` — #10 forks + #12 hanging
- `docs/plans/2026-02-23-wave2-plan2-trapped-mate.md` — #14 trapped + #15 mate patterns
- `docs/plans/2026-02-23-wave2-plan3-backrank-development.md` — #17 back rank + #28 development

**Combined Acceptance Criteria:**
- [ ] `_find_forks` detects defense-aware forks: labels check/royal forks, verifies the fork forces a concession (capturing the forker doesn't solve all threats)
- [ ] `Fork` dataclass has `is_check_fork: bool` and `is_royal_fork: bool` fields
- [ ] King is a valid forker (king forks are real tactics, especially in endgames)
- [ ] `_find_hanging` uses `board.legal_moves` for pinned piece retreat (pinned pieces can move along pin line)
- [ ] `_find_trapped_pieces` checks both sides using null move pattern, not just side to move
- [ ] `_find_mate_patterns` uses `if` (not `elif`) to detect all matching patterns, including boden/double_bishop
- [ ] `_find_back_rank_weaknesses` uses `board.legal_moves` via null move pattern to check king escape, not manual square scanning
- [ ] `analyze_development` counts surviving minors not on home squares (not "home square vacated")
- [ ] All existing tests pass (some may need updating for corrected behavior)
- [ ] New tests cover each bug fix with at least one positive and one negative case

**Dependencies:** Wave 1 complete (get_piece_value, pawn sweep, unified ray motifs all landed)

---

## Detailed Design (reference — implementation details are in the plan files)

### Task 1: Fix fork detection — defense-aware with check/royal labels [Independent]

**Context:** `_find_forks` (lines 755-783) has a wrong value filter `target_val >= piece_val` that misses queen forks (a queen forking two rooks: rook(5) < queen(9), so targets are filtered out). No check fork or royal fork labeling exists.

**Definition of a fork:** A piece attacks 2+ enemy pieces such that the opponent cannot adequately address all threats simultaneously. If the opponent can capture the forking piece and that resolves all threats, it's not a real fork. If one target is the king (check fork), the opponent must deal with check first, which usually means the other target is conceded.

**King as forker:** King forks are valid tactics, especially in endgames. The king moves to a square attacking two enemy pieces; the opponent can only save one. The defense-awareness heuristic handles king forks naturally — the king can't be captured, so the fork always forces a concession.

**Files:**
- Modify: `src/server/analysis.py` (lines 755-783 `_find_forks`, Fork dataclass ~line 498)
- Modify: `tests/test_analysis.py` (add fork tests)

**Step 1: Add fields to Fork dataclass**

Add two boolean fields with defaults to the `Fork` dataclass:
```python
@dataclass
class Fork:
    forking_square: str
    forking_piece: str
    targets: list[str]
    target_pieces: list[str]
    color: str = ""
    is_check_fork: bool = False   # one target is the king
    is_royal_fork: bool = False   # targets include both king and queen
```

**Step 2: Write failing tests**

```python
def test_fork_knight_forks_rook_and_bishop():
    """Classic knight fork — neither target can capture the knight, both are valuable."""
    board = chess.Board("4k3/8/1r6/3N4/5b2/8/8/4K3 w - - 0 1")
    tactics = analyze_tactics(board)
    forks = [f for f in tactics.forks if f.forking_square == "d5"]
    assert len(forks) == 1
    assert set(forks[0].targets) == {"b6", "f4"}

def test_fork_check_fork_labeled():
    """Knight fork with king = check fork."""
    board = chess.Board("4k2r/5N2/8/8/8/8/8/4K3 b - - 0 1")
    tactics = analyze_tactics(board)
    forks = [f for f in tactics.forks if f.forking_square == "f7"]
    assert len(forks) == 1
    assert forks[0].is_check_fork is True

def test_fork_royal_fork_labeled():
    """Knight fork of king and queen = royal fork."""
    board = chess.Board("4k3/2N5/8/q7/8/8/8/4K3 b - - 0 1")
    tactics = analyze_tactics(board)
    forks = [f for f in tactics.forks if f.forking_square == "c7"]
    assert len(forks) == 1
    assert forks[0].is_royal_fork is True
    assert forks[0].is_check_fork is True

def test_fork_king_can_fork():
    """King fork in endgame — king attacks two pieces, opponent can only save one."""
    board = chess.Board("8/8/8/3K4/2r1r3/8/8/7k w - - 0 1")
    tactics = analyze_tactics(board)
    king_forks = [f for f in tactics.forks if f.forking_piece == "K"]
    assert len(king_forks) >= 1

def test_fork_queen_forks_two_rooks():
    """Queen forking two undefended rooks IS a fork when queen is defended."""
    board = chess.Board("4k3/8/1r6/3Q4/5r2/8/3P4/4K3 w - - 0 1")
    # Pd2 defends Qd5 — capturing the queen costs material
    tactics = analyze_tactics(board)
    forks = [f for f in tactics.forks if f.forking_square == "d5" and f.forking_piece == "Q"]
    assert len(forks) >= 1

def test_fork_not_real_if_forker_capturable_and_worth_more():
    """Undefended queen attacking two pawns — capturing the queen solves everything."""
    # The implementing agent should construct a position where an undefended
    # high-value piece attacks two low-value pieces. Capturing it is a win.
    pass  # Implementing agent constructs concrete position
```

Note: the implementing agent should verify each FEN using `python3 -c "import chess; b = chess.Board('FEN'); print(b)"` and adjust positions so the fork geometry works correctly.

**Step 3: Implement defense-aware `_find_forks`**

Replace the current implementation:

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

            # Defense-awareness: a fork is real only if it forces a concession.
            # Heuristic: fork is real if:
            #   (a) one target is the king (check fork — must address check), OR
            #   (b) forker is defended (capturing it loses material), OR
            #   (c) forker's value < max target value (opponent loses more by ignoring)
            # King as forker: can't be captured, so effectively always "defended."
            has_king_target = chess.KING in target_types
            forker_defended = (
                piece.piece_type == chess.KING  # king can't be captured
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
            is_check = has_king_target
            is_royal = has_king_target and has_queen_target

            forks.append(Fork(
                forking_square=chess.square_name(sq),
                forking_piece=piece.symbol(),
                targets=targets,
                target_pieces=target_pieces,
                color=color_name,
                is_check_fork=is_check,
                is_royal_fork=is_royal,
            ))
    return forks
```

**Step 4: Run tests**

```bash
pytest tests/test_analysis.py -k "fork" -v
pytest tests/ -v
```

**Step 5: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: defense-aware fork detection with check/royal fork labels

Removes wrong target_val >= piece_val filter. Forks now verified to force
a concession. King valid as forker. New is_check_fork and is_royal_fork fields."
```

---

### Task 2: Fix hanging piece retreat for pinned pieces [Independent]

**Context:** `_find_hanging` (lines 786-818) has three branches for `can_retreat`: pinned (always False), pawn (legal_moves), other (is_trapped). The pinned branch is wrong — a pinned piece can move along the pin line. A rook pinned along a file can still move up or down that file.

**Files:**
- Modify: `src/server/analysis.py` (lines 786-818 `_find_hanging`)
- Modify: `tests/test_analysis.py` (add hanging tests)

**Step 1: Write failing tests**

```python
def test_hanging_pinned_piece_can_retreat_along_pin_line():
    """A rook pinned along a file can still retreat along that file."""
    # White Rook on e4 pinned to King on e1 by Black Queen on e8.
    # Ne2 attacks Re4. Re4 is pinned to Ke1 by Qe8.
    # But Re4 can legally move to e3, e2 (capture), e5, e6, e7 — all on e-file.
    board = chess.Board("4q3/8/8/8/4R3/8/4n3/4K3 w - - 0 1")
    tactics = analyze_tactics(board)
    hanging_rook = [h for h in tactics.hanging if h.square == "e4"]
    if hanging_rook:
        assert hanging_rook[0].can_retreat is True  # can move along pin line

def test_hanging_pinned_piece_truly_trapped():
    """A piece pinned and surrounded with no legal moves truly can't retreat."""
    # Construct a position where a pinned piece has no legal moves at all.
    # The implementing agent should find or construct such a position.
    pass
```

**Step 2: Fix `_find_hanging`**

Replace the three-branch logic with a single `board.legal_moves` check:

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

Key change: removed separate pinned/pawn/other branches. Single `board.legal_moves` check handles all cases correctly. Also removes the `is_trapped` import from this function.

**Step 3: Run tests**

```bash
pytest tests/test_analysis.py -k "hanging" -v
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: pinned pieces can retreat along pin line in hanging detection

Replaced three-branch logic (pinned/pawn/other) with unified board.legal_moves
check. Pinned pieces now correctly show can_retreat=True when they have legal
moves along the pin line."
```

---

### Task 3: Fix trapped piece detection for both sides [Independent]

**Context:** `_find_trapped_pieces` (lines 833-849) only checks `board.turn` side because `is_trapped` iterates `board.legal_moves` which only generates moves for the side to move. To check the other side, use the null move pattern (`board.push(chess.Move.null())`) to flip the turn.

**Files:**
- Modify: `src/server/analysis.py` (lines 833-849 `_find_trapped_pieces`)
- Modify: `tests/test_analysis.py` (add trapped tests)

**Step 1: Write failing tests**

```python
def test_trapped_detects_non_side_to_move():
    """Trapped pieces should be detected for both sides, not just side to move."""
    # A black bishop trapped on h7 when it's White's turn to move.
    # White pawns on g6 and h6 restrict the bishop to h7/g8.
    board = chess.Board("4k3/7b/6PP/8/8/8/8/4K3 w - - 0 1")
    tactics = analyze_tactics(board)
    trapped = [t for t in tactics.trapped_pieces if t.color == "black"]
    assert len(trapped) >= 1

def test_trapped_still_detects_side_to_move():
    """Existing behavior: trapped pieces for the side to move still detected."""
    # Same position but Black to move — should still find the trapped bishop.
    board = chess.Board("4k3/7b/6PP/8/8/8/8/4K3 b - - 0 1")
    tactics = analyze_tactics(board)
    trapped = [t for t in tactics.trapped_pieces if t.color == "black"]
    assert len(trapped) >= 1
```

**Step 2: Fix `_find_trapped_pieces`**

Use the null move pattern to check both sides:

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
- Loops over both colors instead of just `board.turn`
- Uses `board.push(chess.Move.null())` / `board.pop()` to flip turn temporarily
- Guards against null-move-into-check (skip that side — legal_moves would be meaningless)

**Step 3: Run tests**

```bash
pytest tests/test_analysis.py -k "trapped" -v
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: detect trapped pieces for both sides, not just side to move

Uses null move pattern (push/pop) to check the non-moving side's pieces.
Guards against null-move-into-check positions."
```

---

### Task 4: Fix mate pattern detection — check all patterns [Independent]

**Context:** `_find_mate_patterns` (lines 852-887) uses `elif` chain, stopping after the first match. A checkmate position could match multiple pattern definitions. Using `if` for each ensures all applicable labels are reported.

**Files:**
- Modify: `src/server/analysis.py` (lines 852-887 `_find_mate_patterns`)
- Modify: `tests/test_analysis.py` (add mate pattern tests)

**Step 1: Write failing test**

```python
def test_mate_pattern_boden_always_checked():
    """boden_or_double_bishop_mate should run even if another pattern matched."""
    # Construct a boden's mate position and verify it's detected.
    # The implementing agent should construct a concrete checkmate position
    # matching the boden pattern.
    pass  # Implementing agent constructs specific test position

def test_mate_pattern_detects_known_pattern():
    """Verify each individual pattern detector still works after the elif→if change."""
    # Smothered mate: Ng6# with king surrounded by own pieces
    # The implementing agent should construct one known checkmate position
    # per pattern type and verify detection.
    pass  # Implementing agent constructs specific test positions
```

**Step 2: Fix `_find_mate_patterns`**

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
- `elif` → `if` for each pattern check
- `boden_or_double_bishop_mate` always runs (not gated behind `else`)
- boden/double_bishop remain mutually exclusive (same function returns one or the other)

**Step 3: Run tests**

```bash
pytest tests/test_analysis.py -k "mate_pattern" -v
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: check all mate patterns instead of stopping at first match

Changed elif chain to if statements so all matching patterns are detected.
boden_or_double_bishop_mate now always checked, not gated behind else."
```

---

### Task 5: Fix back rank weakness detection — use legal moves [Independent]

**Context:** `_find_back_rank_weaknesses` (lines 908-945) manually checks if squares one rank forward are blocked by own pieces. This misses squares that are empty but attacked by enemy pieces (king can't move to attacked squares). Using `board.legal_moves` is correct and simpler.

**Files:**
- Modify: `src/server/analysis.py` (lines 908-945 `_find_back_rank_weaknesses`)
- Modify: `tests/test_analysis.py` (add back rank tests)

**Step 1: Write failing tests**

```python
def test_back_rank_weakness_with_attacked_escape_squares():
    """King on back rank with empty escape squares that are all attacked = weakness."""
    # Kg1, pawns g2/h2. f2 is empty but attacked by Bf3. Rd8 provides threat.
    board = chess.Board("3r4/8/8/8/8/5b2/6PP/6K1 w - - 0 1")
    # Forward squares: f2 (attacked by Bf3), g2 (own pawn), h2 (own pawn).
    # King has no safe escape off back rank.
    tactics = analyze_tactics(board)
    br = [w for w in tactics.back_rank_weaknesses if w.weak_color == "white"]
    assert len(br) >= 1

def test_back_rank_no_weakness_when_king_can_escape():
    """King on back rank with a safe escape square = no weakness."""
    board = chess.Board("3r4/8/8/8/8/8/5PPP/6K1 w - - 0 1")
    # Kg1, pawns f2/g2/h2. But f2 is unattacked — wait, f2 has a pawn.
    # Need: Kg1 with at least one forward square open and unattacked.
    board = chess.Board("3r4/8/8/8/8/8/6PP/5RK1 w - - 0 1")
    # Kg1, Rf1, pawns g2/h2. f2 is open and unattacked. King can go to f2.
    # Actually Rf1 blocks f1, not f2. King can go to f2 (open, unattacked).
    # The implementing agent should verify this FEN geometry.
    tactics = analyze_tactics(board)
    br = [w for w in tactics.back_rank_weaknesses if w.weak_color == "white"]
    assert len(br) == 0
```

**Step 2: Fix `_find_back_rank_weaknesses`**

Use null move pattern to check legal king moves off the back rank:

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
- Replaced manual escape-square loop with `board.legal_moves` check
- Uses null move pattern for non-moving side (same as Task 3)
- Checks for king moves that leave the back rank (`rank != back_rank`) — king moves along the back rank are NOT escape
- Guards against null-move-into-check

**Step 3: Run tests**

```bash
pytest tests/test_analysis.py -k "back_rank" -v
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: back rank weakness uses legal_moves instead of manual escape check

Uses null move pattern for non-moving side. Correctly handles attacked
escape squares that the manual piece-checking approach missed.
King moves along the back rank correctly do not count as escape."
```

---

### Task 6: Fix development counting — track surviving minors [Independent]

**Context:** `analyze_development` (lines 1183-1204) increments `w_dev` when the starting square doesn't have the expected piece. If a minor piece is captured (removed from the board), its starting square is vacant and counted as "developed." This is wrong — a captured piece isn't developed.

**Files:**
- Modify: `src/server/analysis.py` (lines 1183-1204 `analyze_development`)
- Modify: `tests/test_analysis.py` (add development tests)

**Step 1: Write failing tests**

```python
def test_development_captured_piece_not_counted():
    """A captured knight should not count as developed."""
    # White's g1 knight has been captured (not on board).
    # b1 knight still on b1 (not developed). Bc1 and Bf1 still home.
    board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKB1R w KQkq - 0 1")
    result = analyze_development(board)
    # Correct: 0 pieces developed (3 still home, 1 captured = not developed)
    assert result.white_developed == 0

def test_development_moved_piece_counted():
    """A knight that moved to f3 should count as developed."""
    board = chess.Board("rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 1")
    # Nf3 is developed. Nb1, Bc1, Bf1 still home.
    result = analyze_development(board)
    assert result.white_developed == 1

def test_development_all_minors_developed():
    """All four minor pieces moved off home squares = 4 developed."""
    board = chess.Board("r1bqk2r/pppppppp/2n1bn2/8/3BB3/2N2N2/PPPPPPPP/R2QK2R w KQkq - 0 1")
    result = analyze_development(board)
    assert result.white_developed == 4
```

**Step 2: Fix `analyze_development`**

Formula: `developed = total_surviving_minors - minors_still_on_home_squares`

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

Captured pieces reduce `total_minors`, not inflate the developed count. Edge case: pawn promotes to knight/bishop → inflates `total_minors` beyond 4. This is correct — a promoted knight on d5 IS a deployed minor piece.

**Step 3: Run tests**

```bash
pytest tests/test_analysis.py -k "development" -v
pytest tests/ -v
```

**Step 4: Commit**

```bash
git add src/server/analysis.py tests/test_analysis.py
git commit -m "fix: development counts surviving minors, not vacated home squares

Captured pieces no longer count as developed. Formula:
developed = total_surviving_minors - minors_on_home_squares"
```

---

## Execution Notes

**Parallelism:** All 6 tasks are fully independent. They modify different functions in `analysis.py` and can be executed by parallel subagents. Each task touches a distinct line range with no overlap:
- Task 1: lines 498 (Fork dataclass) + 755-783 (_find_forks)
- Task 2: lines 786-818 (_find_hanging)
- Task 3: lines 833-849 (_find_trapped_pieces)
- Task 4: lines 852-887 (_find_mate_patterns)
- Task 5: lines 908-945 (_find_back_rank_weaknesses)
- Task 6: lines 1183-1204 (analyze_development)

**Shared pattern:** Tasks 3 and 5 both use the null move pattern (`board.push(chess.Move.null())` / `board.pop()`) to flip the turn for non-moving side analysis. This is the standard python-chess approach — push/pop are paired and don't mutate the board.

**Test strategy:** Each task writes new tests for the specific bug. Existing tests may need minor updates if they tested the old (buggy) behavior — the implementing agent should check each failing test and update if it's asserting incorrect behavior.

**Downstream impact:** These are all internal function fixes. The dataclass shapes are unchanged (Fork gets two new fields with defaults). Downstream consumers in game_tree.py, descriptions.py, motifs.py, and report.py should not need changes, but the implementing agent should verify by running the full test suite.

**Risk:** Task 1 (forks) is the most complex due to defense-awareness logic. If the defense check is too aggressive (filters real forks), fall back to the simpler approach: detect pattern only, label check/royal, skip defense check.
