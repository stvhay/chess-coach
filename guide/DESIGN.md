# Chess Teacher Design

Chess Teacher teaches chess during live play. The student plays against a
pedagogically-motivated opponent while a coaching system watches, intervening at
critical moments with explanations grounded in concrete analysis. Three
subsystems collaborate: Stockfish provides ground-truth evaluation and best
moves, a coded position analyzer extracts structured tactical and positional
facts, and an LLM translates those facts into natural-language coaching. The
result: a teacher that explains *why*, not just *what*.

---

## Why Chess Teacher Exists

Chess players between 800 and 1800 Elo fall between two kinds of tools.

On one side sit engines and puzzle trainers. Stockfish tells you that Nf6 is
+0.3 better than Be7, but never tells you why, or what positional principle you
missed. Puzzle apps drill pattern recognition but disconnect tactics from the
messy, unfolding context of a real game.

On the other side sit video courses and books. A grandmaster can explain the
Sicilian pawn structure beautifully, but when you sit down to play, you are on
your own. The explanation was generic; your position is specific.

Chess Teacher bridges this gap. The student plays a real game. The analysis
targets the position on the board -- not a canned lesson, not a raw engine
number. The coach speaks in natural language, but Stockfish evaluation and coded
positional analysis back every claim. The system never hallucinates a tactic,
because the LLM never evaluates positions itself. It reads structured facts and
explains them.

The emotional job: "I understand what is happening in my games."

---

## Core Design Principle

**The LLM is the teacher persona. It never evaluates positions itself.**

This central architectural constraint shapes everything else. Stockfish provides
ground truth -- evaluations, best moves, forcing lines. The position analyzer
(coded in `analysis.py`) provides structured facts -- pins, forks, pawn
weaknesses, king safety assessments, material imbalances. The LLM receives these
facts as a structured report and translates them into coaching.

Why this separation matters:

- **Correctness.** LLMs hallucinate chess analysis. They confidently describe
  pins that do not exist and miss mates in two. Stockfish does not. Keeping the
  LLM out of evaluation grounds the coaching in reality.

- **Transparency.** Every coaching claim traces back to a specific detection
  function or engine line. When the coach says "your knight is pinned to your
  queen," `_find_ray_motifs()` found that pin and the board state confirmed it.
  The LLM added the words, not the analysis.

- **Separation of concerns.** The position analyzer can be tested with pytest
  against known positions. The LLM prompt can be tuned independently. Neither
  depends on the other's internals.

The coach stays silent on routine moves. It speaks only when something concrete
triggers it -- a blunder, a tactic, a key decision point. Silence is approval.

---

## How the Pieces Fit Together

The student interacts with a browser-based chessboard. Every move flows through
a FastAPI server to an LLM orchestrator, which coordinates Stockfish analysis
and RAG retrieval before generating coaching. The position analyzer sits beneath
Stockfish, computing tactical and positional facts from the raw board state. The
LLM sees only structured reports -- natural-language descriptions of what
changed, what threats exist, and what alternatives the student had -- never raw
FEN strings or engine internals.

```
Browser (chessground + stockfish.wasm)
    |
    v
FastAPI server (uvicorn)
    |
    v
LLM orchestrator
    |                   |
    v                   v
Stockfish engine    RAG (ChromaDB + Ollama)
    |
    v
Position analyzer
(analysis.py -- tactical/positional facts)
    |
    v
Game tree + report
(game_tree.py, descriptions.py, motifs.py, report.py)
```

The browser runs its own Stockfish instance (stockfish.wasm) for the eval bar
and as a fallback when the server is slow. The server-side Stockfish performs
deeper analysis for coaching. The system degrades gracefully: if the LLM goes
down, the game continues without coaching; if server Stockfish goes down, the
browser engine takes over. See [ARCHITECTURE.md](ARCHITECTURE.md) for module
details and [TRADE-OFFS.md](TRADE-OFFS.md) for the reasoning behind these
choices.

---

## The Analysis Pipeline in Brief

When the student makes a move, the system builds a **game tree** rooted at the
decision point -- the position where the student chose. Stockfish generates
candidate continuations. The position analyzer computes tactical motifs (pins,
forks, hanging pieces, mate threats, and more) at each node. A diffing system
compares tactics before and after each move, identifying new threats created, old
threats resolved, and opportunities missed.

These structured facts flow into `serialize_report()`, which produces the
coaching prompt -- a natural-language summary of the position, the student's
move, the alternatives, and what each continuation means. The LLM reads this
report and writes coaching. It adds pedagogical framing, emphasis, and
encouragement -- never analysis.

[ANALYSIS-PIPELINE.md](ANALYSIS-PIPELINE.md) documents the full pipeline.
[DESIGN-THEORY.md](DESIGN-THEORY.md) and [MATH.md](MATH.md) formalize the
position analysis framework.

---

## The Coaching Model in Brief

The coach does not narrate every move. It watches for moments that matter --
mistakes, missed tactics, key strategic decisions, good finds worth reinforcing
-- and speaks only then.

When it speaks, it follows a Socratic gradient: ask first, hint if the student
is stuck, explain if needed. It never lectures unprompted. The student can always
play any move, even against the coach's advice; the coach acknowledges and moves
on.

The opponent is also pedagogically motivated. It selects moves from Stockfish
candidates, filtered by the student's level and the concepts under study. The
opponent does not try to win; it tries to create positions where the student can
learn.

[PEDAGOGY.md](PEDAGOGY.md) details the coaching philosophy.
[UX.md](UX.md) covers interaction flows and the degradation model.

---

## Document Map

| Document | Description |
|----------|-------------|
| [DESIGN.md](DESIGN.md) | This document -- purpose, motivation, design principles, system overview |
| [PEDAGOGY.md](PEDAGOGY.md) | Teaching philosophy: when the coach speaks, what it says, how it adapts |
| [UX.md](UX.md) | Interaction flows, user stories, graceful degradation |
| [UI.md](UI.md) | Interface layout, visual design, component structure |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Software structure, modules, data flow, deployment |
| [ANALYSIS-PIPELINE.md](ANALYSIS-PIPELINE.md) | The chain from board position to coaching prompt |
| [DESIGN-THEORY.md](DESIGN-THEORY.md) | Position analysis formalism -- maps MATH.md concepts to code |
| [TRADE-OFFS.md](TRADE-OFFS.md) | Technology choices, alternatives considered, known limitations |
| [LANDSCAPE.md](LANDSCAPE.md) | Other chess products, related work, how Chess Teacher differs |
| [ROADMAP.md](ROADMAP.md) | Future ideas and planned features |
| [MATH.md](MATH.md) | Theoretical framework for position description graphs |
| [TACTICS.md](TACTICS.md) | User-facing explanation of tactical and positional detection |

---

## Where to Start

- **Building the project?** Start with [ARCHITECTURE.md](ARCHITECTURE.md) for
  the module map and data flow, then [ANALYSIS-PIPELINE.md](ANALYSIS-PIPELINE.md)
  for the coaching generation path.

- **Understanding the teaching approach?** Read [PEDAGOGY.md](PEDAGOGY.md) for
  when and how the coach intervenes, then [UX.md](UX.md) for interaction design.

- **Evaluating the technology?** [TRADE-OFFS.md](TRADE-OFFS.md) explains what
  was chosen and why. [LANDSCAPE.md](LANDSCAPE.md) compares Chess Teacher to
  existing tools.

- **Interested in the analysis math?** [MATH.md](MATH.md) defines the formal
  framework. [DESIGN-THEORY.md](DESIGN-THEORY.md) maps those definitions to
  the actual codebase.
