# The Chess Software Landscape and Where Chess Teacher Fits

A survey of the chess software ecosystem -- engines, analysis platforms,
puzzle trainers, course platforms, and emerging AI tutors -- identifying the
gap Chess Teacher occupies.

---

## 1. Chess Engines

**Stockfish** is the strongest open-source chess engine and has dominated
computer chess since roughly 2018. It combines a highly-optimized alpha-beta
search with NNUE (efficiently updatable neural network) evaluation. Stockfish
provides raw position evaluation (centipawns or mate-in-N), principal
variations (best lines), and multi-PV analysis (top N candidate moves ranked
by strength). It speaks UCI -- a text protocol designed for GUIs, not humans.

**Leela Chess Zero (Lc0)** takes a different approach: a full neural network
trained through self-play, inspired by DeepMind's AlphaZero. Where Stockfish
searches deeply and precisely, Lc0 relies on pattern recognition and
positional intuition. Lc0 sometimes evaluates positions differently from
Stockfish -- preferring long-term structural advantages that Stockfish
underweights at moderate depth. This divergence teaches well (engine
disagreements usually reveal something instructive about the position), but
neither engine explains *why* it prefers a move.

**What engines do well:** Correctness. Given enough depth, Stockfish finds
the best move in virtually any position. It never hallucinates, never
confuses piece colors, never misses a tactic because a positional theme
distracted it.

**What engines lack:** Explanation. The output of `info depth 32 score
cp +47 pv e4 e5 Nf3 Nc6 Bb5 a6` tells you *what* to play but nothing about
*why*. A 1200-rated player staring at Stockfish's top line learns that e4 is
good but not that it controls the center, opens lines for the bishop and
queen, and prepares castling. The engine assumes you can read the line and
grasp its implications -- an assumption that holds for grandmasters and fails
for everyone else.

Chess Teacher uses Stockfish as its ground-truth oracle. The engine evaluates
positions, generates candidate moves, and validates tactical sequences. But
engine output never reaches the student directly. It passes through a
position analyzer (coded tactical and positional detection) and then through
an LLM that translates structured analysis into natural language.

---

## 2. Analysis Platforms

### Lichess Analysis Board

Lichess is the largest open-source chess platform. Its analysis board lets
you paste a FEN or PGN, run Stockfish in your browser (via WASM), and
explore engine lines interactively. The evaluation bar shows who is winning.
Arrows show the engine's preferred moves. You can click through variations,
request deeper analysis, and explore the opening database.

For post-game review, Lichess runs server-side analysis that annotates each
move with symbols: good move, inaccuracy, mistake, blunder. It displays the
evaluation graph over the game and highlights the largest swings.

**Strengths:** Free, fast, open-source, browser-native. The analysis board is
the best free tool for exploring positions with engine assistance. The opening
explorer (drawing from millions of games) provides statistical context for
opening moves.

**Limitations:** The annotations are engine output with classification labels.
Lichess tells you that 14...Bxf2 was a blunder and that 14...Nd5 was best,
but never explains *why* the knight move is better. A student sees "you should
have played Nd5" and thinks "I guess I should memorize that" rather than
understanding the positional logic. The evaluation graph shows *that* the
position swung but never explains *what caused* the swing.

### Chess.com Game Review

Chess.com's game review is the most popular post-game analysis tool. Free
users get limited reviews per day; premium subscribers get unlimited access.
The review classifies moves (brilliant, great, best, good, book, inaccuracy,
mistake, blunder), shows accuracy percentages, and highlights key moments.

**Strengths:** Polished UI. The "brilliant move" classification and accuracy
percentage gamify analysis in a way that motivates casual players. Beginners
find the interface more approachable than Lichess.

**Limitations:** The same fundamental gap as Lichess -- it shows what happened
but never why. The accuracy percentage encourages playing "engine moves"
rather than understanding positions. The "brilliant" classification misleads:
it usually means "the only move that avoids losing," which differs from a move
that demonstrates deep understanding. Premium features gate basic analysis
behind a subscription.

### ChessBase

ChessBase is the professional's tool -- a database application storing
millions of games, supporting deep Stockfish/Lc0 analysis, and integrating
with opening preparation workflows. Grandmasters use it to prepare for
opponents, build repertoires, and analyze adjourned games.

**Strengths:** The most powerful analysis environment available. Deep database
integration, reference games, novelty detection, correspondence analysis
features.

**Limitations:** Designed for professionals and serious tournament players.
The UI is complex, the learning curve steep, the price high (several hundred
dollars). A research tool, not a teaching tool.

---

## 3. Puzzle Trainers

### Lichess Puzzles

Lichess hosts over 5.7 million puzzles extracted from real games, tagged by
theme (fork, pin, skewer, deflection, etc.) and rated by difficulty. The
puzzle system uses Glicko-2 rating: your puzzle rating rises when you solve
hard puzzles and falls when you miss easy ones.

Chess Teacher integrates the Lichess puzzle database directly. The
`PuzzleDB` class in `puzzles.py` wraps a local SQLite copy of the full
Lichess puzzle set with FTS5 theme search, enabling queries like "give me a
1200-rated pin puzzle" without network dependency.

**Strengths:** Massive volume, community-curated quality, accurate ratings,
free. Theme tagging enables focused practice ("I want to work on discovered
attacks").

**Limitations:** Puzzles are isolated positions. You see a board state and
find the winning move (or sequence). You get no context -- you never learn
how the position arose, what strategic decisions created the tactic, or how
to engineer similar opportunities in your own games. Feedback is binary: you
found the move or you missed it. No explanation of *why* the tactic works,
what makes the position ripe for it, or what the opponent did wrong to
allow it.

### Chess Tempo

Chess Tempo is a dedicated puzzle server known for accurate difficulty
calibration and a large problem set. It offers standard tactics training,
endgame puzzles, and a "guess the move" mode for full games. Premium tiers
add custom problem sets and spaced-repetition scheduling.

**Strengths:** Accurate difficulty ratings, endgame training (which Lichess
puzzles underserve), clean interface focused entirely on training.

**Limitations:** The same isolation problem as all puzzle trainers. Tactical
pattern recognition improves, but the student must bridge the gap to
real-game decision-making alone.

### The Puzzle Training Gap

Puzzle training works. Studies consistently show that tactical pattern
recognition improves with practice, and puzzle ratings correlate with playing
strength. But puzzles train a specific skill -- "given that a tactic exists,
find it" -- which differs from the game skill of recognizing *when* a tactic
might exist and engineering positions where tactics arise.

Coaching bridges the gap between "I can solve a pin puzzle" and "I notice pin
opportunities in my games." Chess Teacher addresses this by presenting
tactics in game context, explaining the positional features that made the
tactic possible, and connecting individual moments to broader strategic
themes.

---

## 4. Course Platforms

### Chessable

Chessable dominates the chess course market. It applies spaced repetition
(MoveTrainer) to chess openings, tactics, and endgames. Authors (often
grandmasters) create courses that students learn through interactive
move-by-move drills.

**Strengths:** The spaced repetition model excels at memorizing opening lines.
High-quality courses from strong authors. The interactive format beats video
because you practice moves rather than watch them.

**Limitations:** Memorization, not understanding. MoveTrainer drills the
*sequence* of moves but never the *reasoning*. When your opponent deviates
from the book line -- which happens immediately at amateur level -- you are
on your own. The course cannot respond to a novel position because the
content is static. Courses are also expensive ($20-100+) and represent a
single author's perspective.

### Chess.com Lessons

Chess.com offers a library of interactive lessons on openings, tactics,
strategy, and endgames. Lessons combine text explanation, interactive board
positions, and quizzes. Premium subscription required.

**Strengths:** Well-produced, accessible to beginners, integrated into the
Chess.com ecosystem.

**Limitations:** Passive consumption. The student reads an explanation, sees
a position, and plays the prompted move. The lesson cannot adapt to the
student's existing knowledge. It cannot follow up on a mistake with a
targeted explanation because the script is fixed.

### Video Instruction

YouTube and Twitch have created a generation of chess content creators --
GothamChess, Daniel Naroditsky, Eric Rosen, Hikaru Nakamura, and many
others. High-quality free video instruction has arguably advanced chess
education more than any software tool.

**Strengths:** Human explanation. A strong player narrating their thought
process ("I'm looking at d5 because the knight would be a monster there, but
first I need to deal with this pin on c6") delivers exactly the reasoning
that engines cannot provide and students need to hear.

**Limitations:** Passive. You watch, absorb a fraction, try to apply it, and
forget most of it. No feedback loop. The instructor cannot adapt to your
specific weaknesses. Video explanation is linear -- it cannot branch based on
what you already understand.

### The Course Platform Gap

Course platforms deliver expert knowledge in a fixed format. They teach well
when the student's questions align with what the author anticipated. They
fail when the student needs something the author omitted, when the student
needs the same concept explained differently, or when the student needs to
see how a concept applies to a novel position.

---

## 5. AI Chess Tutors

The emerging space, and mostly bad.

### The Hallucination Problem

Multiple ChatGPT-based chess bots and tutors have appeared since 2023. The
typical architecture: user pastes a position or PGN, LLM responds with
analysis and advice. The fundamental problem is that LLMs cannot reliably
evaluate chess positions. They hallucinate -- claiming pieces stand on squares
where they do not, missing obvious tactics, suggesting illegal moves,
inventing variations that contradict the position.

This has nothing to do with model size or training data. Chess evaluation
requires combinatorial search (which positions arise after each candidate
move, recursively). Transformer attention is not search. An LLM might
pattern-match a position to similar positions in its training data, but it
cannot verify its pattern match by calculating -- it just guesses with high
confidence.

The result is worse than no analysis: the student receives
authoritative-sounding nonsense. "Your knight on f3 controls the center
nicely" when the knight sits on g1. "Black has a strong pin on the e-file"
when no pin exists. This erodes trust and teaches wrong lessons.

### Chess.com's AI Features

Chess.com has integrated AI explanations into its game review feature. An LLM
generates the explanations, which appear alongside (and presumably draw from)
Stockfish analysis. Quality varies -- some explanations help, others merely
rephrase the engine evaluation in slightly more natural language without
adding insight.

**Strengths:** Integration with Stockfish analysis provides some grounding.
Chess.com has the resources to iterate on prompt engineering and fine-tuning.

**Limitations:** The explanations narrate engine output after the fact rather
than coach the student through positional thinking. They describe what the
engine found rather than teach the student how to think about the position.
How deeply the LLM reads from the engine versus generates independently
remains opaque.

### Research Projects

Several academic projects have explored LLM-chess integration: using LLMs to
generate natural-language commentary on chess games (trained on grandmaster
annotations), using LLMs to explain engine disagreements, and using LLMs as
interfaces to chess engines. Most remain research prototypes.

### What Chess Teacher Does Differently

Chess Teacher's architecture enforces a strict separation: the LLM never
evaluates positions, never judges moves as good or bad, never calculates
variations, never determines whether a pin exists.

Instead, the system works in three layers:

1. **Stockfish** evaluates positions, generates candidate moves, and
   provides principal variations. This is the ground truth.

2. **The position analyzer** (`analysis.py`, ~955 lines of coded logic)
   detects concrete positional and tactical features: material balance, pawn
   structure, king safety, piece activity, pins, forks, skewers, discovered
   attacks, hanging pieces, overloaded defenders, mate patterns, and more.
   These deterministic functions operate on board state. They never guess.
   The analysis produces typed dataclasses, not free text.

3. **The LLM** receives structured analysis (the output of
   `serialize_report()`) and translates it into natural-language coaching.
   It explains what the analysis found, connects it to broader concepts, and
   adapts its language to the student's level.

The LLM's input is facts -- "White has an absolute pin on c6: the bishop on
b5 pins the knight on c6 to the king on e8" -- not positions. It cannot
hallucinate a pin that the analyzer missed because it never sees the board
directly. It can only explain pins that the position analyzer actually
detected.

This grounding architecture is Chess Teacher's core technical contribution.
See DESIGN.md (planned) for the full value proposition.

---

## 6. The Lichess Relationship

Chess Teacher builds on open-source infrastructure, and Lichess is the
largest source.

### Components Used

**chessground** is the Lichess board UI library. It handles rendering,
piece dragging, animation, arrows, and square highlighting. Chess Teacher
uses it as the frontend board component. Building a chess board UI from
scratch would take months and produce a worse result; chessground is mature,
well-tested, and handles edge cases (promotion dialogs, premove, touch
devices) that are easy to get wrong.

**Lichess puzzler tactical detection.** Chess Teacher vendors utility
functions from the `ornicar/lichess-puzzler` repository -- specifically
`is_hanging`, `is_trapped`, `is_in_bad_spot`, `can_be_taken_by_lower_piece`,
and mate pattern detectors (back rank, smothered, Arabian, hook, Anastasia,
dovetail, Boden/double bishop). These are tracked in
`src/server/lichess_tactics/upstream.json` with AST hashes for drift
detection. Vendoring lets Chess Teacher use battle-tested detection logic
while adapting it for static board analysis (the upstream code targets puzzle
mainlines, which assume a sequence of moves).

**Lichess puzzle database.** The full Lichess puzzle set (~5.7 million
puzzles) lives in a local SQLite database with FTS5 indexing. The `PuzzleDB`
class in `src/server/puzzles.py` provides async queries by theme, rating
range, and random sampling. This gives Chess Teacher a massive library of
tactical positions for training exercises without network dependency.

**python-chess.** While not a Lichess project, python-chess is maintained by
Niklas Fiekas, a core Lichess contributor, and is the standard Python library
for chess programming. Chess Teacher uses it for board representation, move
generation, UCI engine communication, PGN parsing, and the bitboard
primitives that underlie the position analyzer.

### Planned Integration

**Lichess Studies.** The foundation design describes exporting coaching
analysis as Lichess Studies -- annotated PGN with commentary, arrows, and
highlighted squares pushed via the Lichess API. Students could revisit
lessons in Lichess's study viewer, share them, and access them on any device.

**Game import.** Analyzing games the student played on Lichess (or elsewhere)
through the same coaching pipeline: import a PGN, run position analysis,
generate a coaching report.

### The Relationship

Lichess provides open-source chess infrastructure that would take years to
build independently. Chess Teacher consumes this infrastructure and adds a
layer Lichess does not provide: LLM-grounded coaching during live play. The
projects complement each other rather than compete. See TRADE-OFFS.md
(planned) for the rationale behind specific component choices.

---

## 7. The Gap Chess Teacher Fills

The chess software landscape has a specific structural gap. Existing tools
cluster into three categories, each with a characteristic limitation:

### Tools that give answers without explanation

Engines and engine-backed analysis platforms (Lichess analysis, Chess.com
game review, ChessBase) tell you *what* to play. They are correct. They are
also opaque. The student sees the right move but never the reasoning behind
it. This works for strong players who can read a variation and grasp its
implications. It fails for the 800-1800 Elo range -- precisely the audience
that needs the most help.

### Tools that explain without grounding

LLM-based chess bots explain fluently but cannot verify their explanations.
They sound like coaches but think like autocomplete. When the LLM says "this
position features a strong pin on the e-file," the student cannot tell
whether the pin exists. The LLM cannot tell either -- it predicts plausible
chess commentary rather than analyzes a position.

### Tools that teach passively

Course platforms, video instruction, and puzzle trainers deliver real chess
knowledge. The content is often excellent. But the delivery is fixed: the
student watches, memorizes, or solves isolated positions. No adaptation, no
response to novel positions, and no coaching during the activity that matters
most -- playing games.

### What Chess Teacher combines

Chess Teacher sits at the intersection:

```
                    Grounded          Explanatory
                    (engine-backed)   (natural language)
                   +----------------------------------+
  Engines          | yes              | no             |
  Analysis boards  | yes              | minimal        |
  LLM bots         | no               | yes            |
  Chess Teacher    | yes              | yes            |
                   +----------------------------------+
```

And it delivers this during live play, not after:

```
                    Real-time         Adaptive
                    (during play)     (responds to student)
                   +----------------------------------+
  Courses          | no               | no             |
  Puzzle trainers  | no               | minimal        |
  Game review      | no (post-game)   | no             |
  Chess Teacher    | yes              | yes            |
                   +----------------------------------+
```

The specific combination -- grounded analysis, natural-language explanation,
real-time delivery during play, adaptation to student level -- is the gap.
Each individual capability exists somewhere. No existing tool combines all
four.

### Why the gap exists

Building this requires solving three hard problems simultaneously:

1. **Reliable position analysis** beyond raw evaluation -- detecting and
   classifying tactical and positional features in structured form. This is
   the 955-line position analyzer plus vendored Lichess detection code.

2. **LLM grounding** -- ensuring the language model explains only what the
   analysis found, never inventing features. This is the architectural
   separation between analysis, structured report, and language generation.

3. **Real-time coaching UX** -- deciding when to speak, what to say, and
   how much to say during a live game without disrupting flow. This is the
   coaching intervention design (speak at critical moments, stay silent on
   routine moves, adapt intensity to student level).

Engines solve (1) partially (evaluation but not feature detection). LLMs
solve none of them reliably alone. Course platforms sidestep all three by
using pre-authored content. Chess Teacher tackles all three together.

---

## Summary

| Category | Examples | Strength | Gap |
|----------|----------|----------|-----|
| Engines | Stockfish, Lc0 | Correctness | No explanation |
| Analysis platforms | Lichess, Chess.com, ChessBase | Visual, integrated | Show what, not why |
| Puzzle trainers | Lichess puzzles, Chess Tempo | Pattern recognition | Isolated from games |
| Course platforms | Chessable, Chess.com lessons | Expert knowledge | Static, passive |
| AI tutors | ChatGPT bots, Chess.com AI | Natural language | Hallucinate positions |
| **Chess Teacher** | -- | Grounded + explanatory + real-time | The thing being built |

Chess Teacher replaces none of these tools. Students will still use Lichess
for games, Chessable for repertoire memorization, and YouTube for
entertainment. Chess Teacher fills a specific role: the interactive coach who
watches you play, understands what is happening on the board (via Stockfish
and coded analysis), and explains it in words you can learn from (via a
grounded LLM). That role does not exist in the current landscape.
