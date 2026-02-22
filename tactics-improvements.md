# Tactical Detection Improvements Wanted

Requests from coaching quality iteration. The tactics detection session should pick these up.

- [x] Hanging piece detection should distinguish between "student's piece is undefended" (bad for student) and "opponent's piece is capturable" (good for student). Currently `hanging_piece` is ambiguous about who benefits.
  - **Done**: Added `color` field to `HangingPiece` dataclass ("white"/"black").
- [x] Pin detection should distinguish absolute pins (pinned to king, piece cannot legally move) from relative pins (pinned to queen/rook, piece can move but probably shouldn't). Absolute pins are much more severe.
  - **Done**: Added `is_absolute` field to `Pin` dataclass (True when pinned to king).
- [x] Add "mate threat" detection: when a side threatens checkmate on the next move, flag it as a motif even before the checkmate appears in the PV. This helps coaching scenarios like "ignoring a mate threat."
  - **Done**: Added `MateThreat` dataclass and `_find_mate_threats()` detector. Iterates legal moves, checks if any deliver checkmate.
- [x] Add "back rank weakness" detection: when a king has no escape squares on the back rank and the opponent has a rook/queen that could deliver mate. This is a positional motif, not just a tactical one.
  - **Done**: Added `BackRankWeakness` dataclass and `_find_back_rank_weaknesses()` detector. Checks king on back rank + forward squares blocked by own pieces + opponent has heavy piece.
- [x] Discovered attack significance filtering: pawn-reveals-rook x-rays (e.g., e-pawn reveals a1-rook on the a-file) exist in nearly every opening position and are pedagogically worthless. Consider filtering these at the detection level or adding a `significance` field so downstream can filter.
  - **Done**: Added `significance` field to `DiscoveredAttack` ("low" for pawn-blocking-rook targeting pawns, "normal" otherwise). Downstream can filter on this.
