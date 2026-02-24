# Pedagogy: How Chess Teacher Teaches

Chess Teacher rests on one conviction: you learn chess by playing, not by memorizing theory. The student plays real games against a coached opponent and receives feedback at the moments that matter. Otherwise, the coach stays silent --- silence signals approval.

This document describes the coaching model, the systems that support it, and how they adapt to different skill levels.

## Teaching philosophy

Most chess education tools work backwards. They start from a database of positions and ask the student to find the right move. Chess Teacher starts from the student's actual game and intervenes only when something warrants comment.

The three principles:

1. **Learn by doing.** The student plays complete games. Concepts arise in context, never in isolation.
2. **Coach, don't lecture.** The system speaks only at critical moments. Every intervention serves a specific pedagogical purpose: correcting a mistake, reinforcing a pattern, or illuminating a decision.
3. **Ground everything in analysis.** The coach never improvises chess knowledge. Stockfish evaluation and coded tactical/positional analysis back every claim about the position. The LLM explains; it never evaluates.

The student should feel a patient human coach watching over their shoulder --- one who speaks up when it matters and stays quiet when they play well.

This contrasts deliberately with two common alternatives. Engine analysis tools (Lichess analysis board, chess.com game review) show raw evaluations and top engine lines --- accurate but overwhelming and unexplained. Traditional chess instruction presents curated positions out of context --- clear but disconnected from the student's actual play. Chess Teacher occupies the middle ground: real-time coaching grounded in engine analysis, delivered within the student's own game.

## When the coach speaks

The coach does not comment on every move. It watches for specific triggers and stays silent otherwise.

| Trigger | Coach behavior |
|---|---|
| Critical mistake (blunder/mistake) | Explains what went wrong and what the stronger move achieves. Red arrow on the played move, green arrow on the best move. |
| Inaccuracy | Notes the imprecision and briefly explains what the better move does. |
| Brilliant move | Praises the student. Blue arrow on the move, yellow arrows on tactical targets (fork targets, etc). |
| Key decision point | Highlights an important moment with meaningfully different continuations. |
| Repertoire-relevant moment | Connects the position to the opening or structure the student studies. |
| Good move in a sharp position | Brief reinforcement: "Good --- controlling d5 before it becomes an outpost." |
| Pattern repetition | Escalates: hint, then explain, then show an example from the knowledge base. |

**When quiet:** The student plays a reasonable move in a non-critical position. No comment. The coach's absence *is* the feedback --- it means the student plays well.

The gating logic lives in `coach.assess_move()`. It computes centipawn loss between the position before and after the student's move (both evaluations from White's perspective, adjusted for the student's color), classifies the move into one of five quality levels (brilliant, good, inaccuracy, mistake, blunder), and returns `None` for routine good moves. Only non-routine moves produce a `CoachingResponse` with a message, arrows, highlights, and severity score.

The classification thresholds are fixed: blunder at 200+ centipawns lost, mistake at 100+, inaccuracy at 50+. The engine's top choice in a sharp position earns the "brilliant" classification.

Board annotations reinforce the verbal feedback. Arrows follow a consistent color language: red marks the student's mistake, green marks the better move, blue marks a brilliant find, and yellow highlights tactical targets like fork victims. Highlights mark specific squares. The system keeps annotations sparse --- one or two key ideas per intervention, never a rainbow of lines covering the board.

## What the coach says

The LLM receives a structured prompt, not a raw position. It never sees a FEN string or an evaluation number. Instead, `report.serialize_report()` generates a report containing:

1. **Student color** and game PGN up to the decision point.
2. **Position description** --- threats, opportunities, and observations rendered from coded analysis (material imbalance, pawn structure, king safety, piece activity, tactical motifs).
3. **Student move** --- the move played, its classification (good/inaccuracy/mistake/blunder), what changed tactically, the engine continuation, and the material result.
4. **Alternatives** --- stronger moves the engine found, with the same structure: tactical consequences, continuations, and material outcomes.
5. **RAG context** --- relevant knowledge base content if available.

Each tactical motif (fork, pin, skewer, hanging piece, discovered attack, mate threat, etc.) has a dedicated renderer in `motifs.py`. The renderer uses ownership context ("your knight" vs "their knight") so the LLM need not infer piece colors from notation.

The system prompt (`prompts/system.py`) targets specific LLM failure modes discovered during coaching quality iteration:

- **RULES**: The LLM may reference only pieces, squares, and tactics that appear in the analysis. It must not invent tactical themes.
- **SEVERITY**: Blunders require direct language ("this loses significant material"), not hedging ("a bit risky"). Inaccuracies must not receive praise.
- **PERSPECTIVE**: Tactics arrive pre-labeled as opportunities or threats. The LLM must preserve the classification.
- **ACCURACY**: The LLM must use exact notation from the analysis and must not describe a pawn push as a capture.

This architecture makes the LLM a translator, not an analyst. It converts structured facts into conversational English. It cannot hallucinate a fork the analysis missed, because it never sees the board --- only the analysis output.

The tactic diffing system (`descriptions.diff_tactics()`) deserves emphasis. It compares tactical motifs *before* the student's move to those *after*, identifying new motifs, resolved motifs, and persistent motifs. The LLM prompt includes only *new* motifs --- tactics the student's move created or allowed. This prevents the coach from describing a pre-existing pin as though the student just walked into it. Each motif keys on its structurally significant squares (not its text label), so a pin on e4 and a pin on d5 track independently even though both are "pins."

Three buckets further categorize motifs: opportunities (good for the student), threats (good for the opponent), and observations (structural features like back-rank weakness or x-ray alignments lacking immediate tactical consequence). The LLM sees these categories directly and must use them as given.

For the full pipeline from position to prompt, see [ANALYSIS-PIPELINE.md](ANALYSIS-PIPELINE.md).

## ELO adaptation

Five profiles control analysis depth and communication style. They live in `elo_profiles.py` as `EloProfile` dataclass instances:

| Profile | ELO range | Screen depth | Validate depth | Concept depth | CP threshold |
|---|---|---|---|---|---|
| Beginner | 600--800 | 3 | 12 | 2 ply | 200 cp |
| Intermediate | 800--1000 | 4 | 14 | 3 ply | 175 cp |
| Advancing | 1000--1200 | 4 | 16 | 4 ply | 150 cp |
| Club | 1200--1400 | 6 | 18 | 5 ply | 125 cp |
| Competitive | 1400+ | 6 | 20 | 6 ply | 100 cp |

What varies:

- **Screen depth and breadth** (`screen_depth`, `screen_breadth`): How many candidate moves the engine evaluates in the initial shallow pass, and how deeply. Beginners get a wider but shallower search (15 lines at depth 3); competitive players get a narrower but deeper one (8 lines at depth 6).
- **Validate depth** (`validate_depth`): How deeply the engine confirms top candidates. Ranges from depth 12 (beginner) to depth 20 (competitive).
- **Concept depth** (`max_concept_depth`): How many plies of continuation the student can calculate. A beginner sees 2-ply tactics (one move and one response); a competitive player sees 6-ply combinations. Tactics requiring deeper calculation than the student's concept depth drop in priority.
- **Recommend depth** (`recommend_depth`): How far into alternatives the system annotates. Ranges from 4 ply (beginner) to 10 ply (competitive).
- **Centipawn threshold** (`cp_threshold`): How much centipawn loss still qualifies as a reasonable alternative. Beginners tolerate 200 cp; competitive players see only alternatives within 100 cp.

The default profile is "intermediate" (800--1000 ELO). The student selects their level through a dropdown in the settings menu, and the API receives the profile when starting a new game. The profile shapes the entire analysis pipeline: a beginner gets fewer, simpler alternatives explained in shorter tactical chains; a competitive player gets more alternatives analyzed to greater depth.

The profiles should affect not just *what* the system analyzes but *how* it communicates. A beginner should hear "your knight can capture the rook" while a competitive player should hear "Nxd4 wins the exchange after the discovered attack on the queen." This per-profile language variation remains future work --- the structured report currently matches across all profiles, and the LLM adapts its tone based on the preamble instruction to "be concise."

### How the opponent adjusts

The opponent module (`opponent.py`) selects moves from Stockfish candidates filtered by phase-dependent centipawn thresholds:

| Game phase | CP threshold | Rationale |
|---|---|---|
| Opening | 30 cp | Theory is sharp. Bad opening moves create unrecoverable disadvantages. |
| Middlegame | 75 cp | Wider tolerance lets the LLM choose pedagogically interesting positions. |
| Endgame | 20 cp | Endgames demand precision. Stockfish plays directly with a depth cap. |

When an LLM teacher is available, it selects among filtered candidates based on which move creates the most instructive position. In the endgame or when only one candidate survives filtering, the system skips LLM selection and plays the engine's top move directly.

The system prompt for opponent selection (`OPPONENT_SYSTEM_PROMPT`) asks the LLM to prefer principled development in openings, instructive imbalances in middlegames, and to avoid engine-like tricks above the student's level.

## Teachability ranking

When the student makes a move, the system finds not just the engine's best move but the most *teachable* alternatives. The function `_rank_nodes_by_teachability()` in `game_tree.py` scores each candidate move by the pedagogical value its continuation contains.

The heuristic walks each candidate's continuation chain (the sequence of best responses) and accumulates an interest score:

**Positive signals (what makes a move worth showing):**

- **New motif types per ply.** Each new tactical motif (fork, pin, skewer, etc.) appearing in the continuation earns points. Motifs within the student's concept depth count more than those requiring deep calculation.
- **High-value motifs.** Double checks and trapped pieces score 3.0 points. X-ray attacks, exposed kings, overloaded pieces, and capturable defenders score 2.0. Mate patterns score 5.0.
- **Material changes.** Captures gaining more than 50 centipawns within the concept depth earn 2.0 points.
- **Checkmate.** A line ending in checkmate *for the student* earns 100 points; checkmate *against the student* earns -50 points. The system adjusts for side (Stockfish's `score_mate` always reports from White's perspective).
- **Sacrifices.** Lines where the student gives up 200+ centipawns of material and then recovers (or delivers mate) earn a 4.0 bonus.
- **Positional themes.** Passed pawns, isolated pawns, and open files near the king each earn a small bonus.

**Negative signals (what makes a move less worth showing):**

- **Deep-only motifs.** Tactics appearing only beyond the student's concept depth incur a -2.0 penalty per motif type. A 6-ply combination teaches nothing to a beginner who can see only 2 plies.
- **Large evaluation loss.** Moves losing more than 150 centipawns versus the best move incur a -3.0 penalty. The system skips objectively bad moves.

After scoring, the top candidates (controlled by `validate_breadth` in the ELO profile) receive a deep validation pass with the engine; the rest are discarded. This two-pass architecture (screen wide, validate deep) keeps engine usage practical while ensuring the coaching tree contains genuinely interesting alternatives.

### A concrete example

Suppose the student plays Nf3 but the engine's top three alternatives are d4, e4, and c4. The system walks each continuation:

- **d4** leads to a fork on e5 at ply 2 and a discovered attack at ply 3. Score: fork (3.0 per early motif) + discovered (2.0 per moderate motif) + 3.0 per early motif type x 2 = 11.0.
- **e4** leads to a quiet position with an isolated pawn at ply 4. Score: positional theme (1.0) + 3.0 per early motif type x 1 = 4.0.
- **c4** leads to a queen trade at ply 2 with equal material. Score: material change (2.0) = 2.0.

The system shows d4 as the "Stronger Alternative" because it produces the most tactically instructive continuation within the student's concept depth. The LLM then explains the fork and discovered attack in plain language.

### Limitations

The heuristic is deliberately simple. It ignores the student's history (a fork stays interesting even after ten forks this session). It does not weight motifs by difficulty or novelty for the specific student. It treats all positions equally, regardless of whether the student studies tactics or positional play. The trained teachability model will address all of these. The heuristic serves as a strong baseline that ensures the coaching tree always contains the most tactically rich alternatives --- the right default.

For the formal specification of motif detection, see [DESIGN-THEORY.md](DESIGN-THEORY.md). The trained teachability model that will eventually replace this heuristic appears in [ROADMAP.md](ROADMAP.md).

## Coaching intensity

The full design specifies three coaching levels along an autonomy gradient:

| Level | Behavior |
|---|---|
| Guide me | Coach speaks at every critical moment, asks questions, explains. |
| Watch me | Coach speaks only on significant mistakes or when asked. |
| Let me play | Coach stays silent. Student clicks "explain" for input. Post-game review available. |

The default is "Guide me." The system adapts implicitly over time --- when the student handles a pattern correctly and consistently, the coach stops commenting on that pattern. A student who never blunders pins eventually stops hearing about pins.

**Current implementation:** The MVP implements a single mode ("Guide me") with fixed intensity determined by the ELO profile. The autonomy gradient and implicit adaptation remain future work. The gating function (`assess_move`) applies the same classification thresholds to every move regardless of history, and the system evaluates each moment independently without tracking pattern repetition across the session.

The student can always play any legal move, including moves the coach advises against. The coach never blocks. In the full design, it would acknowledge the choice, let the game continue, and revisit the decision if it caused trouble later. In the MVP, it simply lets the student proceed.

## The Socratic sequence

The full coaching model uses a four-step sequence:

1. **Ask** --- "What do you think about the d5 square?"
2. **Hint** --- "Look at where White's knight can go in two moves."
3. **Explain** --- Full explanation with board annotations.
4. **Never lecture unprompted** --- Long explanations only when asked or after the ask/hint sequence completes.

This sequence requires conversation state (tracking what the student has heard and whether they responded), absent from the MVP. The MVP implements step 3 only: when the coach has something to say, it explains directly.

The Socratic sequence is the primary target for the next coaching iteration. It transforms the student from passive recipient to active participant --- the student thinks before hearing the answer.

Implementing the full sequence requires:

- **Conversation state**: tracking what the coach has asked, whether the student responded, and how many escalation steps have occurred.
- **Student response parsing**: determining whether the student's free-text answer shows understanding or confusion.
- **Pause mechanics**: the coach must pause the game clock (or the interaction flow) while awaiting a student response, without making the experience feel sluggish.
- **Graceful fallback**: if the student ignores the question and simply plays a move, the coach must let the game continue. It should either treat the move as the response or defer the question.

## What grounds the coaching

Chess Teacher uses a three-layer architecture with clearly bounded roles:

**Stockfish** provides evaluation. It answers "which moves are good?" and "how good is this position?" through centipawn scores and principal variations. It never explains.

**Coded analysis** (`analysis.py`, ~955 lines) provides tactical and positional facts. It answers "what is happening in this position?" through concrete detections: forks, pins, skewers, discovered attacks, hanging pieces, trapped pieces, mate threats, mate patterns, pawn structure, king safety, piece activity, development, space, center control, file control, and diagonal control. These deterministic functions examine the board state using `python-chess` primitives. They never consult Stockfish and never guess.

**The LLM** provides language. It answers "how do I explain this to the student?" by receiving the structured output of the first two layers and translating it into natural-language coaching. It never evaluates positions, detects tactics, or examines the board.

This separation is the project's central design constraint. The LLM cannot hallucinate a tactic because it never sees the position --- only the analysis. Stockfish cannot confuse the student because its output never appears directly. The coded analysis cannot harbor undetected errors because it is deterministic and thoroughly tested (673 tests at last count).

The pipeline from position to coaching message runs through these layers in sequence:

1. `build_coaching_tree()` calls Stockfish for evaluations and `analyze_tactics()` for tactical facts.
2. `describe_position()` and `describe_changes()` render those facts into categorized natural language (opportunities, threats, observations).
3. `serialize_report()` arranges the descriptions into a sectioned prompt.
4. The LLM receives the prompt and produces a 2--3 sentence coaching message.

The LLM never accesses a FEN string, a raw evaluation number, or any information outside the report. This is by design.

### Why not let the LLM see the board?

Large language models can play chess at an intermediate level and can sometimes identify tactics. But they hallucinate freely --- inventing nonexistent forks, misidentifying which side benefits from a tactic, confusing piece colors, and describing captures that are actually pawn pushes. Coaching quality iteration surfaced all of these failure modes.

Withholding the raw position from the LLM eliminates these failure modes structurally rather than through prompt engineering alone. The system prompt still contains guardrails (the RULES, SEVERITY, PERSPECTIVE, and ACCURACY sections) as defense in depth, but the primary protection is architectural: the LLM simply cannot discuss what it has not been told.

This approach trades flexibility for reliability. The LLM cannot notice an unusual pattern the coded analysis missed. If `analysis.py` lacks detection for a specific tactic type, the coach will never mention it. That tradeoff is acceptable: a coach that sometimes misses subtle patterns far surpasses one that sometimes invents them.

### Degradation behavior

When components fail, the system degrades gracefully:

- **LLM unavailable**: The game continues without coaching. The student sees "Coach is thinking..." then a timeout message. Coaching resumes when the LLM recovers.
- **RAG unavailable**: The coach still works but with less context. Explanations draw on analysis alone, without knowledge-base enrichment.
- **Server Stockfish unavailable**: The browser's stockfish.wasm takes over move generation and evaluation. The transition is seamless.
- **All engines unavailable**: The game pauses. This is the only hard stop.

The system never shows a modal error dialog. Degradation messages appear naturally in the coach chat panel, as though the coach acknowledges its own limitations: "I'm having trouble connecting --- give me a moment."

For the complete analysis pipeline specification, see [ANALYSIS-PIPELINE.md](ANALYSIS-PIPELINE.md). For the motif detection formalism, see [DESIGN-THEORY.md](DESIGN-THEORY.md).
