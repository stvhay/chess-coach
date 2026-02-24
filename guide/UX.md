# UX: User Experience and Interaction Model

How a player experiences Chess Teacher, from opening the app to finishing a game.

For the software architecture behind these interactions, see [ARCHITECTURE.md](ARCHITECTURE.md). For the analysis pipeline powering coaching feedback, see [ANALYSIS-PIPELINE.md](ANALYSIS-PIPELINE.md). For pedagogical rationale, see [PEDAGOGY.md](PEDAGOGY.md).

---

## 1. User Model

**Who uses this.** Chess players rated roughly 800--1800 Elo who want to study openings and positional concepts by *playing*, not by reading or watching.

**What they know.** They can move pieces, read algebraic notation, and have heard of pawn structure, piece activity, and king safety. They recognize these terms but cannot consistently apply the ideas in their own games. They may know what a pin is but still hang pieces to one.

**What they want.** To understand *why* -- not just the best move, but the plan it supports, and what went wrong when they miss it. Static puzzle trainers give answers without context. Pure engine analysis gives evaluations without explanations. They want a coach who watches them play and speaks up when it counts.

**Emotional job.** Confidence. "I understand what's happening in my games." The app succeeds when a player finishes a session feeling they learned something concrete, not when they achieve a high accuracy score.

**Context.** Sitting at a computer, focused, unhurried. This is a study tool, not a blitz arena. Sessions last 15--45 minutes. The player may work through a specific opening repertoire or explore a positional theme.

---

## 2. Core Interaction Loop

The fundamental cycle: play, receive feedback at critical moments, keep playing.

```
1. Student selects an Elo profile (controls coaching depth and opponent behavior)
2. Game begins -- student plays White
3. Opponent (server-controlled) responds with pedagogically selected moves
4. On critical moves, coach intervenes: text explanation + board arrows
5. On routine moves, coach stays silent -- silence signals approval
6. Game ends -- checkmate, stalemate, or draw
```

The coach does not narrate every move. Most moves produce no coaching output. The student learns to read silence as "you're doing fine" and to pay attention when the coach speaks.

---

## 3. User Flows

### 3.1 Starting a New Game

**What the student does:** Opens the app and clicks "New Game" in the top bar. An Elo profile dropdown in the settings menu (hamburger icon) lets them choose their level: beginner (600--800), intermediate (800--1000), advancing (1000--1200), club (1200--1400), or competitive (1400+). The default is intermediate.

**What happens underneath:** The frontend calls `createGame(depth, eloProfile)` in `api.ts`, which POSTs to `/api/game/new`. The server's `GameManager.new_game()` creates a `GameState` with the selected Elo profile and returns a session ID, the starting FEN, and status "playing". The frontend's `GameController.newGame()` resets the chess.js instance, clears coaching history, and syncs the chessground board. The browser Stockfish engine begins evaluating the starting position.

**What the student sees:** A fresh board, pieces in the starting position, ready to play White. The eval bar shows the initial assessment. No coaching message -- the game has not started yet.

**Target time:** Board ready and interactive within 2 seconds of clicking "New Game". The `/api/game/new` call requires no engine work, so the browser engine's initial eval is the bottleneck.

### 3.2 Making a Move and Receiving Coaching

**What the student does:** Drags a piece to make a move, or clicks the origin and destination squares.

**What happens underneath:** Chessground validates the move against legal destinations computed by `legalDests()` in `game.ts`. If legal, `GameController.handleMove()` applies the move locally in chess.js, updates the board immediately (so the student sees the piece land without waiting), then sends the move to the server via `sendMove(sessionId, moveUci)`.

On the server, `GameManager.make_move()` runs a multi-step pipeline:

1. **Pre-move evaluation.** Stockfish evaluates the position *before* the student's move at coaching depth (default 12 ply). This establishes the baseline.
2. **Move application.** The server applies the move to its board.
3. **Post-move evaluation.** Stockfish evaluates the new position.
4. **Move assessment.** `assess_move()` in `coach.py` computes centipawn loss and classifies the move: brilliant, good, inaccuracy, mistake, or blunder. Good moves return `None` -- the coach stays silent.
5. **Coaching enrichment** (non-routine moves only). `_enrich_coaching()` builds a game tree via `build_coaching_tree()`, queries RAG for relevant knowledge, serializes a structured prompt, and sends it to the LLM for a natural-language explanation. This pipeline enforces a 20-second timeout so the game never freezes.
6. **Opponent move selection.** `select_opponent_move()` picks the opponent's reply (see section 3.5).

The response includes: the new FEN, both moves in SAN, game status, and coaching data (quality label, message text, arrows, highlights, severity score).

**What the student sees:** Their piece lands immediately. The board locks briefly while the server thinks (the `thinking` flag disables move input). Then the opponent's piece moves, the board unlocks, and if coaching triggered, the coach's message appears in the right panel with arrows drawn on the board.

### 3.3 Making a Mistake

When the student plays a move that loses significant material or positional advantage, the coaching pipeline activates.

**Classification thresholds** (from `coach.py`):
- **Blunder:** 200+ centipawns lost
- **Mistake:** 100--199 centipawns lost
- **Inaccuracy:** 50--99 centipawns lost

**What the student sees:** A red arrow on their move, a green arrow showing the best alternative, and a coaching message in the chat panel. The LLM generates this message from the analysis pipeline's structured report -- it explains the error in natural language, referencing specific pieces, squares, and tactical themes.

For example, after hanging a knight to a fork: the board shows a red arrow on the student's move and a green arrow on the best alternative. The coaching panel explains the fork threat, names the pieces involved, and suggests what to look for in similar positions.

**Board annotations follow a consistent color scheme:**
- Red arrow: the student's problematic move
- Green arrow: the best alternative
- Blue arrow: a brilliant move
- Yellow arrows: tactical targets (fork victims, etc.)

The severity score (0--100, mapped from centipawn loss) could drive future UI decisions like animation intensity or sound. Currently the coaching data includes it for the frontend to use as it sees fit.

### 3.4 Playing a Good Move

Most good moves produce no coaching output -- `assess_move()` returns `None` and the coach stays silent. Constant feedback is noise. The student learns to interpret silence as "keep going."

When the student finds the best move in a sharp position, the system classifies it as "brilliant." The student sees a blue arrow on their move, yellow arrows pointing to tactical targets, and a brief reinforcement message: "Excellent! Nxe5 is the best move here." with tactical context if relevant.

The coaching pipeline's enrichment step runs even for brilliant moves, so the LLM can explain *why* the move works -- not just that it was best.

### 3.5 Opponent Move Selection

The opponent does not play at engine strength. A Stockfish-strength opponent would play perfect moves the student could never understand, creating positions with no learning value. Instead, the opponent plays moves chosen for pedagogical richness.

**The selection process** (in `opponent.py`):

1. **Candidate generation.** Stockfish produces the top 5 moves at depth 12.
2. **Phase detection.** `detect_game_phase()` classifies the position as opening, middlegame, or endgame.
3. **Centipawn filtering.** Moves within a phase-dependent threshold of the best move survive:
   - Opening: 30 cp (tight -- stay close to theory)
   - Middlegame: 75 cp (looser -- allow instructive positions)
   - Endgame: 20 cp (tight -- accuracy matters)
4. **LLM selection** (when available and multiple candidates survive). The LLM receives a position summary and the filtered candidates, then picks the move that best serves the student's learning. It returns the chosen move and a rationale (logged, not shown to the student).
5. **Fallback.** If the LLM is unavailable, only one candidate survives, or it is the endgame, the system uses the top engine move.

The result: the opponent plays reasonable, understandable chess -- moves whose ideas are visible at the student's calculation depth.

### 3.6 Game Ending and Review

When the game ends (checkmate, stalemate, draw, or claimable draw), the server returns the final status and result string ("1-0", "0-1", or "1/2-1/2"). The frontend's status callback fires and the UI displays the outcome.

**Move history navigation.** The student can step backward and forward through the game using `jumpToPly()`, `stepForward()`, and `stepBack()` in `GameController`. At each ply, the board shows the position and any coaching annotations generated for that move (stored in `coachingByPly`). The browser engine re-evaluates the viewed position so the eval bar updates during review.

The student can revisit the coach's feedback in context -- see the board as it was when the mistake happened, with the same arrows and message.

---

## 4. API Interaction Model

The frontend is a static JS application talking to a FastAPI server over JSON APIs. No server-rendered HTML, no WebSocket connection, no streaming -- each interaction is a request-response cycle.

### Key Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/game/new` | POST | Create a new game session. Accepts `depth` and `elo_profile`. Returns `session_id`, `fen`, `status`. |
| `/api/game/move` | POST | Submit a player move. Accepts `session_id` and `move` (UCI). Returns `fen`, both moves in SAN, `status`, `result`, and `coaching` data. |
| `/api/engine/evaluate` | POST | Raw Stockfish evaluation. Accepts `fen` and `depth`. Returns score, best move, PV. |
| `/api/engine/best-moves` | POST | MultiPV analysis. Accepts `fen`, `n`, `depth`. Returns top N moves with scores. |
| `/api/analysis/position` | POST | Full positional analysis. Accepts `fen`. Returns structured analysis report. |
| `/api/puzzle/random` | GET | Random puzzle(s). Accepts optional `theme`, `rating_min`, `rating_max`, `limit`. |
| `/api/health` | GET | Health check. Returns `{"status": "ok"}`. |

### Request-Response Cycle for a Move

```
Frontend                          Server
   |                                |
   |-- POST /api/game/move -------->|
   |   { session_id, move }         |
   |                                |-- Stockfish: eval before
   |                                |-- Apply move
   |                                |-- Stockfish: eval after
   |                                |-- assess_move() -> coaching?
   |                                |-- [if coaching] build_coaching_tree()
   |                                |-- [if coaching] RAG query
   |                                |-- [if coaching] LLM explain
   |                                |-- select_opponent_move()
   |                                |-- Apply opponent move
   |<-- MoveResponse ---------------|
   |   { fen, player_move_san,      |
   |     opponent_move_uci/san,     |
   |     status, result, coaching } |
```

The entire pipeline runs synchronously from the frontend's perspective -- one POST, one response. The server enforces a 20-second `asyncio.wait_for` timeout on coaching enrichment. The frontend's `sendMove()` enforces a 30-second `AbortController` timeout. If the server takes too long, the frontend catches the timeout and continues the game locally (graceful degradation).

### Coaching Data Shape

When coaching is present, the response includes:

```json
{
  "quality": "blunder",
  "message": "Moving the knight to a5 loses it to the bishop...",
  "arrows": [
    { "orig": "c6", "dest": "a5", "brush": "red" },
    { "orig": "c6", "dest": "e5", "brush": "green" }
  ],
  "highlights": [],
  "severity": 85
}
```

The `quality` field is one of: brilliant, good, inaccuracy, mistake, blunder. The `message` holds the LLM's natural-language explanation. Arrows and highlights are chessground drawing primitives that the frontend renders directly onto the board.

---

## 5. Student Disagreement

The student can always play any legal move. The coach never blocks input, never forces a move, never locks the board to demand the "right" move. `legalDests()` in `game.ts` computes all legal moves from chess.js, and any legal move is accepted.

When the student plays a move the coach would not have recommended:

1. The pipeline assesses the move normally.
2. If the move is a mistake, the coach explains what went wrong and shows the alternative.
3. The game continues from the new position. The student never takes back the move.

The coach acknowledges reality: the student made a choice, the position changed, and both sides play from here. This respects the student's autonomy and mirrors real game conditions -- tournament chess has no takebacks.

The full design (not yet implemented in MVP) includes revisiting: if the student ignores coach advice and trouble emerges several moves later, the coach connects the current problem to the earlier decision. "Remember when you played ...a5? This is what I was concerned about." This requires conversation state tracking, planned but not yet built.

---

## 6. Alternative Line Exploration (Future)

In the full design, the student will ask "What if I had played Nf6?" The system would:

1. Rewind the board to the relevant position.
2. Show the alternative line briefly -- a few moves of how the game might have continued.
3. Return to the current game position.
4. Retain the context for future reference.

This requires board state branching in the frontend (`GameController` currently tracks a linear game history via chess.js). The server's game tree architecture (`GameTree`/`GameNode` in `game_tree.py`) already supports branching analysis -- the gap is the frontend and the API, which lack an endpoint for "analyze this alternative from a previous position."

The move navigation that exists today (`jumpToPly`, `stepForward`, `stepBack`) is a foundation: the student can already review earlier positions and see the coaching generated for each. The missing piece is the ability to play forward from an earlier position into an alternative branch.

---

## 7. Failure Handling

The system degrades in layers. Each failing layer peels off a capability, but the game continues until both chess engines are unavailable.

### Degradation Layers

```
Full experience (server Stockfish + LLM + RAG + browser Stockfish)
  |
  +-- RAG unavailable: coach still explains, with less contextual depth
      |
      +-- LLM unavailable: game continues, no coaching text, arrows still generated
          |
          +-- Server Stockfish unavailable: browser engine takes over for eval + moves
              |
              +-- Browser Stockfish unavailable: game pauses
```

### What the Student Sees at Each Level

| Component | Fails | Fallback Behavior | Visible to Student |
|---|---|---|---|
| RAG (ChromaDB/Ollama embeddings) | Coach works without retrieval-augmented context | Nothing -- explanations are slightly less rich |
| LLM (Ollama) | Coaching enrichment times out or returns null; `_enrich_coaching` logs a warning | "Coach is thinking..." then silence. Game continues normally. |
| Server Stockfish | Frontend `sendMove()` fails; `handleMove()` catches the error | Game continues in local-only mode. Browser engine provides eval. |
| Browser Stockfish (WASM) | `BrowserEngine` unavailable | Eval bar disappears. Server still works for opponent moves. |
| Both engines | No moves can be generated | Game pauses. "Engine unavailable." |

### Design Principles

- **No modal error dialogs.** Failures appear as natural coach messages in the chat panel or as subtle UI changes (eval bar disappearing).
- **Silent auto-retry.** The system retries failed connections without prompting the student. When services recover, coaching resumes.
- **One hard stop.** Both chess engines down is the only state that pauses the game, because neither legal move validation nor opponent move generation is possible.
- **Timeouts prevent freezing.** Server-side: 20-second `asyncio.wait_for` on coaching enrichment. Client-side: 30-second `AbortController` on the move request. If the server is slow, the frontend catches the timeout and lets the game continue.
- **State is trivially recoverable.** Game state is a FEN string and move history -- both serializable and reconstructable. Degradation risks no persistent state.

---

## 8. Success Criteria

Performance and experience targets that determine whether the UX works.

### Response Times

| Metric | Target | Rationale |
|---|---|---|
| Game start (new board ready) | < 2 seconds | `/api/game/new` requires no engine work; browser engine init is the bottleneck |
| Move response (opponent replies) | < 5 seconds | Includes two Stockfish evals + opponent selection; student sees their move land immediately |
| Coaching message appears | < 8 seconds after move | Includes game tree construction, RAG query, LLM generation; the move and opponent response arrive first |
| Coaching enrichment timeout | 20 seconds (hard limit) | After this, the game returns without LLM coaching |

### Silence Ratio

The coach should speak on roughly 15--25% of student moves. Speaking on every move creates noise. Never speaking provides no value.

Silence signals deliberate approval. The student should internalize: "when the coach is quiet, I'm doing okay."

The current implementation achieves this through `assess_move()`: routine good moves (centipawn loss under 50, not the best move in a sharp position) return `None`, and the coaching pipeline is skipped entirely. No LLM call, no arrows, no message.

### Opponent Move Speed

The student should never perceive the opponent as slow. The opponent's move should appear within 3 seconds of the student's move landing on the board. The student's move applies to the local board immediately (before the server call), so the interface feels responsive even if the server takes a moment.

If the server is unreachable, the game continues locally -- the student can keep moving pieces. The `catch` block in `handleMove()` handles this: "Server move failed -- game continues locally."

### Board Interactivity

The board locks only during the server round-trip (the `thinking` flag in `GameController`). The lock prevents the student from making another move before the opponent responds. Outside this window, the board is always interactive -- the student can drag pieces freely with immediate visual feedback from chessground's legal move highlighting.
