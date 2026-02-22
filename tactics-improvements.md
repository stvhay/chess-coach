# Tactical Detection Improvements Wanted

Requests from coaching quality iteration. The tactics detection session should pick these up.

- Hanging piece detection should distinguish between "student's piece is undefended" (bad for student) and "opponent's piece is capturable" (good for student). Currently `hanging_piece` is ambiguous about who benefits.
- Pin detection should distinguish absolute pins (pinned to king, piece cannot legally move) from relative pins (pinned to queen/rook, piece can move but probably shouldn't). Absolute pins are much more severe.
- Add "mate threat" detection: when a side threatens checkmate on the next move, flag it as a motif even before the checkmate appears in the PV. This helps coaching scenarios like "ignoring a mate threat."
- Add "back rank weakness" detection: when a king has no escape squares on the back rank and the opponent has a rook/queen that could deliver mate. This is a positional motif, not just a tactical one.
- Discovered attack significance filtering: pawn-reveals-rook x-rays (e.g., e-pawn reveals a1-rook on the a-file) exist in nearly every opening position and are pedagogically worthless. Consider filtering these at the detection level or adding a `significance` field so downstream can filter.
