# Chess Tactics & Position Analysis

How Chess Teacher detects and explains tactical and positional patterns.

Chess Teacher analyzes every position through three layers: [Stockfish](https://stockfishchess.org/) evaluates positions and finds best lines, [python-chess](https://python-chess.readthedocs.io/) generates legal moves and represents the board, and our analysis module detects the tactical and positional motifs described below. Several detection functions come from the [Lichess puzzler](https://github.com/ornicar/lichess-puzzler) codebase. The coaching LLM never invents chess analysis — it explains what these systems find.

---

## Tactical Motifs

Tactics are concrete sequences where one side forces a material or positional gain. Chess Teacher detects these in every position and highlights them when relevant to the student.

### Fork

A single piece attacks two or more enemy pieces simultaneously, forcing the opponent to address one threat while conceding the other.

- **Check fork**: One target is the king. The opponent must handle check first, usually conceding the other target.
- **Royal fork**: The targets include both king and queen — the most devastating variant.

Detection is *defense-aware*: a fork counts only when it genuinely forces a concession. If the opponent can capture the forking piece and resolve all threats, no fork exists. The king can fork, especially in endgames — since it cannot be captured, its forks always force a concession.

### Pin

A long-range piece (bishop, rook, or queen) attacks an enemy piece that cannot move without exposing a more valuable piece behind it on the same line.

- **Absolute pin**: The pinned piece shields the king and cannot legally leave the ray — python-chess enforces this through its legal move generator.
- **Relative pin**: The pinned piece shields a valuable piece (queen, rook) but *can* legally move. Moving is legal but costly.

Classification: if the shielded piece is the king, the pin is absolute regardless of the pinned piece's value. Otherwise, the pinned piece must be worth less than the piece behind it to qualify.

### Skewer

The reverse of a pin: a long-range piece attacks a valuable piece along a line, and when that piece moves, a less valuable piece behind it falls.

- **Absolute skewer**: The front piece is the king, forced to move.

Classification: king in front makes an absolute skewer. A front piece strictly more valuable than the rear piece makes a skewer. Equal or lower front-piece value makes an x-ray attack — nothing is forced.

### Discovered Attack

Moving one piece reveals an attack from a second piece behind it along the same line. A strong discovered attack requires the moving piece to *also* threaten at its destination.

Significance, in descending order:

1. **Discovered check** — the revealed attack hits the king. Always significant.
2. **Discovered capture** — the moving piece captures material.
3. **Discovered attack** — the moving piece gives check or attacks a valuable target.
4. **Battery** — the piece leaves the ray without creating an independent threat. A structural alignment, not a forcing tactic.

The blocker must have at least one legal move off the ray (python-chess handles pin restrictions automatically). A slider blocking a same-type slider on the same ray counts as a battery, not a discovered attack.

### Double Check

Two pieces give check simultaneously — typically a discovered attack where both the moving piece and the revealed slider attack the king. Only the king can move; blocking and capturing are impossible against two checking pieces.

### X-Ray

A long-range piece attacks or defends through one or more intervening pieces to a square or piece beyond.

A single unified ray-walking algorithm detects all ray-based motifs (pins, skewers, discovered attacks, x-rays). For each slider, every ray direction is walked once, and the two pieces found along the ray classify according to this table:

| Intervening piece | Beyond piece | Classification |
|---|---|---|
| Enemy | Enemy king | Absolute pin |
| Enemy (lower value) | Enemy (higher value) | Relative pin |
| Enemy king | Enemy | Absolute skewer |
| Enemy (higher value) | Enemy (lower value) | Skewer |
| Enemy | Enemy (equal or lower) | X-ray attack |
| Enemy | Friendly | X-ray defense |
| Friendly (can leave ray + threatens) | Enemy | Discovered attack |
| Friendly (can leave ray, no threat) | Enemy | Battery |

**X-ray defense**: a slider defends a friendly piece *through* an enemy piece. If the enemy piece moves or falls, the defense becomes direct.

### Hanging Piece

A piece undefended or insufficiently defended — capturable for free or at a profit. Detection uses x-ray-aware defense evaluation from the Lichess puzzler's `is_hanging` function, which catches x-ray defenders that `board.attackers()` misses.

Retreat options are evaluated through python-chess's legal move generator, which handles pinned pieces correctly: a pinned piece can retreat along the pin line but not off it.

### Trapped Piece

A piece with no safe square — every legal move loses material. Detection uses the Lichess puzzler's `is_trapped` function. Both sides are checked regardless of whose turn it is, using a null-move technique for the non-moving side.

### Overloaded Piece

A piece defending two or more targets simultaneously. An attack on any one target forces it to abandon at least one other. Detection identifies sole defenders of multiple attacked squares, counting back-rank defense and mate-threat blocking as defensive duties.

### Capturable Defender

A piece defending a valuable target that can itself be captured, collapsing the defense. Detection identifies the least valuable attacker as the capturer and verifies the defender has a legal move to the defended square (compensating for python-chess's pin-blind `board.attackers()`).

---

## Checkmate Patterns

When checkmate occurs, Chess Teacher identifies the pattern. Detection uses functions from the Lichess puzzler codebase.

| Pattern | Description |
|---|---|
| **Back rank mate** | A rook or queen mates along the opponent's first rank while the king is trapped behind its own pawns. |
| **Smothered mate** | A knight mates a king surrounded by its own pieces — no escape squares exist. |
| **Arabian mate** | A rook and knight coordinate: the rook on the edge, the knight covering escape squares. |
| **Hook mate** | A rook mates with a knight and pawn restricting escape — the pawn "hooks" the king into the mating net. |
| **Anastasia mate** | A rook and knight mate a king on the board's edge, the knight cutting off escape along a file or rank. |
| **Dovetail mate** | A queen mates where the king's two diagonal escape squares are blocked by its own pieces — a "dovetail" shape. |
| **Boden's mate** | Two bishops mate on criss-crossing diagonals, typically after a queen sacrifice opens the lines. |
| **Double bishop mate** | Two bishops coordinate to mate, without requiring Boden's classic criss-cross diagonal pattern. |

---

## Positional Concepts

Positional evaluation concerns long-term strengths and weaknesses — slower-burning than tactics. Chess Teacher evaluates these factors as structured data that the coaching LLM translates into advice.

### Material

Standard piece values: pawn = 1, knight = 3, bishop = 3, rook = 5, queen = 9. The king has no fixed exchange value — callers handle it explicitly per context ("priceless" in safety calculations, zero in trades).

**Bishop pair**: Two bishops qualify as a pair only if they occupy opposite-colored squares (one light, one dark). Detection uses python-chess's `BB_LIGHT_SQUARES` and `BB_DARK_SQUARES` bitboards — two bishops on same-colored squares are not a pair.

### Pawn Structure

A two-pass sweep classifies every pawn: first pass collects per-file pawn data for both colors; second pass annotates each pawn from that data.

| Property | Definition |
|---|---|
| **Isolated** | No friendly pawns on either adjacent file. Cannot be pawn-defended — a lasting weakness. |
| **Doubled** | Two or more friendly pawns on the same file. Usually weak: they block each other's advance. |
| **Passed** | No enemy pawns ahead on the same or adjacent files. Can march to promotion unobstructed — especially powerful in endgames. |
| **Backward** | The stop square (one rank ahead) is attacked by an enemy pawn, and no friendly pawn on adjacent files stands at the same rank or behind. The pawn cannot safely advance. |
| **Chain member** | A friendly pawn stands diagonally behind, forming a pawn chain. Well-supported. |
| **Chain base** | Supports a pawn diagonally ahead but receives no chain support itself. The base is a target — destroy it and the chain collapses. |

**Pawn islands**: groups of pawns separated by empty files. Fewer islands mean healthier structure, since each group supports itself.

### King Safety

King safety assessment draws on features from Stockfish's king danger model, adapted for coaching explanations rather than centipawn scoring:

- **King zone attacks**: Enemy pieces attacking squares around the king.
- **Weak squares**: Squares near the king attacked by the enemy and undefended by friendly pawns.
- **Safe checks**: Squares where the enemy can check without losing the checking piece.
- **Pawn storm**: Enemy pawns advancing toward the king on nearby files.
- **Pawn shelter**: Quality of the friendly pawn shield. Three shielding pawns is ideal; zero is alarm-level.
- **Knight defender**: A friendly knight in the king zone adds significant defensive value.
- **Queen absent**: Without an attacking queen, king danger drops sharply (Stockfish weights this at -873).

These features combine into a composite danger score that decides whether king safety warrants mention. The individual features drive the explanation ("your king is exposed because the g-pawn advanced, leaving weak squares on f3 and h3").

### Piece Activity and Mobility

Each piece (knight, bishop, rook, queen) receives a mobility score — the count of useful squares it can reach. The mobility area excludes impractical squares:

- Squares occupied by own pawns
- Squares attacked by enemy pawns (moving there hangs the piece)
- The own king's square

A qualitative label follows from each piece's mobility count relative to thresholds for its type (e.g., a knight with fewer than 3 squares is "restricted"; more than 5 is "active"). Thresholds derive from Stockfish's MobilityBonus tables.

**Centralization** measures a piece's distance from the center (d4, d5, e4, e5). Centralized pieces control more of the board.

### Center Control

The four central squares (d4, d5, e4, e5) are analyzed individually. For each square, pawn attacks and piece attacks are counted separately for both sides, and occupation is tracked.

This produces specific coaching — "White dominates d5 with 3 attackers against 1" — rather than vague summaries.

Caveat: `board.attackers()` ignores pins, so a pinned piece may count as an attacker even though it cannot legally move to that square. The coaching impact of one extra attacker is negligible; the tradeoff is accepted.

### Space

Space advantage measures how many squares a side controls in enemy territory. Following Stockfish, only the central files (c through f) count — edge files contribute little.

- Per-square attacker counts determine net control (not just "any attacker present")
- Pieces in enemy territory earn occupation credit
- Pawn space (durable) is distinguished from piece influence (temporary)

### Development

Development counts how many minor pieces (knights and bishops) have left their starting squares: *surviving minors minus minors still home*. A captured piece does not count as developed — it is gone.

### Files and Diagonals

- **Open file**: No pawns of either color. Rooks and queens thrive here.
- **Semi-open file**: Only one side's pawns are absent. A rook pressures the remaining enemy pawn.
- **Long diagonals**: The two corner-to-corner diagonals (a1-h8, a8-h1) are especially valuable for bishops, particularly in fianchetto structures.

### Back Rank Weakness

A king on its first rank with no escape squares risks back rank mate. Detection uses python-chess's legal move generator — not manual square-checking — to verify the king cannot leave the back rank, correctly handling enemy-controlled escape squares. The weakness is flagged only when the opponent has a rook or queen to exploit it.

### Exposed King

A king in an open area with inadequate pawn cover and piece support. Distinct from back rank weakness — an exposed king can stand anywhere on the board.

### Mate Threat

One side can deliver checkmate on the next move. Detection iterates all legal moves and checks each for checkmate — a pure tactical fact from python-chess's move generator and `is_checkmate()`, requiring no engine evaluation.

---

## How Detection Feeds Coaching

The analysis module produces structured data — dataclasses with typed fields, not prose. This data flows through four stages to reach the student:

1. **Analysis** detects motifs in each position
2. **Game tree** compares motifs before and after the student's move, identifying what changed
3. **Descriptions** translate motif data into natural-language fragments
4. **Report** assembles the fragments into a structured prompt for the coaching LLM
5. **LLM** speaks to the student — explaining what happened, what was missed, and what to consider

The LLM never sees raw board positions or FEN strings. It receives pre-analyzed, pre-described facts. If the analysis module found no fork, the LLM cannot invent one.
