# UI Design

Chess Teacher's interface balances two moods. Around the board: clean,
functional, information-dense -- a tool. In the coaching panel: warmer,
conversational, approachable -- a teacher sitting next to you. The dark theme
grounds both moods and keeps the board as the visual centerpiece.

This document covers visual design, layout, component structure, and frontend
architecture. For interaction flows and coaching behavior see [UX.md](UX.md).
For browser-side runtime architecture see [ARCHITECTURE.md](ARCHITECTURE.md).
For technology choice rationale (snabbdom over React, etc.) see
[TRADE-OFFS.md](TRADE-OFFS.md).


## Design Direction

The governing idea is **warmth blended with utility**. The coaching panel uses
conversational language, color-coded severity, and comfortable spacing to feel
like a human tutor. The board area, eval bar, move list, and analysis display
use monospace type, tight grids, and muted chrome to recede. The board is the
hero element.

Key principles:

- **Flat depth strategy.** Borders and subtle background shifts distinguish
  panels -- never drop shadows. Only the board commands visual weight.
- **Sparse annotations.** Board arrows and highlights communicate one or two
  ideas at a time, never a rainbow.
- **Silence is approval.** The coaching panel stays quiet during routine play.
  When it speaks, the color-coded border draws the eye.


## Color Palette

| Token         | Value      | Role                                  |
|---------------|------------|---------------------------------------|
| Background    | `#1a1a2e`  | Page background, board surround       |
| Panel         | `#16213e`  | Header, coaching panel, right panel   |
| Deep panel    | `#0f1729`  | Input fields, code blocks, move rows  |
| Button idle   | `#1e3a5f`  | Menu buttons, promotion buttons       |
| Button hover  | `#2a5080`  | Interactive hover state               |
| Border        | `#333`     | Panel edges, dividers                 |
| Text primary  | `#e0e0e0`  | Body text, move notation              |
| Text muted    | `#888`     | Section labels, secondary info        |
| Text dim      | `#666`     | Move numbers, footer, timestamps      |
| Green accent  | `#4ade80`  | Good moves, active states, connected  |
| Yellow        | `#fbbf24`  | Inaccuracies, thinking state          |
| Orange        | `#fb923c`  | Mistakes                              |
| Red           | `#f87171`  | Blunders, errors, game over           |

**Why dark?** Chess boards look best on dark backgrounds -- the convention
across Lichess, chess.com, and most analysis tools. A dark foundation also
reduces visual competition with board squares and piece SVGs. The coaching
severity colors (green through red) read clearly against dark panels without
heavy contrast adjustments.


## Typography

Two type families divide the interface into prose and data.

**Geometric sans** -- `Inter`, falling back through the system sans stack
(`-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`). Coach messages,
status text, menu labels, and the page title use this face. Readable at 13px
body size. Section labels use 11px small-caps with 1px letter spacing for quiet
hierarchy.

**Monospace** -- `JetBrains Mono`, falling back to `Fira Code` and the system
monospace. Move notation, eval scores, PV lines, engine status, FEN input,
keyboard shortcut references, and debug prompts use this face. Chess notation
is essentially code -- fixed-width type aligns columns and makes move numbers
scan naturally.

Font sizes stay small throughout. The title is 16px. Body text is 13-14px.
Labels and debug text drop to 10-11px. This is intentional: the board
dominates; text recedes.


## Layout

The layout is a four-column CSS grid centered in the viewport:

```
+--------------------------------------------------+
|  Chess Teacher                        [hamburger] |  <- header (44px)
+-------------+----+----------------+--------------+
|             |    |                |              |
|   Coach     |Eval|   Chessground  |  Right panel |
|   panel     |bar |   board        |  (analysis   |
|             |    |                |   + moves)   |
|             |    |                |              |
+-------------+----+----------------+--------------+
|  engine: ready                                    |  <- footer (28px)
+--------------------------------------------------+
```

`static/index.html` defines the grid as `grid-template-columns: 1fr auto
auto 1fr`. The two `auto` columns hold the eval bar (24px fixed) and the board
(viewport-height-driven). The two `1fr` columns hold the coaching panel and
right panel, sharing remaining horizontal space equally.

**Board sizing** anchors the layout. A CSS custom property `--board-size`,
computed as `calc(100vh - var(--header-h) - var(--footer-h) - var(--pad) * 2)`,
fills available vertical space after subtracting the 44px header, 28px footer,
and 16px padding on each side. All flanking panels match this height.

The **header** is a flex row: title left, hamburger button right, 44px tall,
panel-colored background. The **footer** is a monospace status line for
browser engine state (green when connected, red on error), 28px tall.

**Spatial hierarchy** from outside in: page background (#1a1a2e) > panel
backgrounds (#16213e) > deep insets (#0f1729 for inputs, alternating move
rows). Borders are 1px solid #333 everywhere. Border radius is 8px on panels
and buttons, 4px on inputs and smaller elements -- soft enough to feel
approachable, not so rounded as to look playful.


## Component Structure

The frontend has five TypeScript modules under `src/frontend/`. Each owns a
distinct concern. No framework manages the DOM -- `main.ts` constructs
elements via `document.createElement`, and chessground manages its own
internal DOM.

### Chessground Board (`board.ts`)

`createBoard()` initializes a chessground instance inside a container element.
It configures the starting FEN, white orientation, constrained (non-free)
movement, drag-and-drop with ghost pieces, and 200ms animation duration. The
`onMove` callback wires piece drops into the GameController.

Chessground handles all board rendering internally: square coloring, piece
positioning via CSS transforms, drag interaction, legal move dots, last-move
highlights, and check indicators. `index.html` overrides the board square
colors to a cool blue-gray (`#8ca2ad` base with `#546e7a` dark squares at 25%
opacity) via an inline SVG background on `cg-board`.

Piece images are cburnett SVGs, base64-encoded directly in `chessground.css`.
Zero external HTTP requests load piece assets -- everything ships in the CSS
bundle. The SVGs come from the chessground npm package's bundled assets; the
build script in `package.json` concatenates `chessground.base.css`,
`chessground.brown.css`, and `chessground.cburnett.css` into
`static/chessground.css`.

### Eval Bar (`eval.ts`)

`BrowserEngine` wraps Stockfish WASM (v18, lite single-threaded build, ~7MB
vendored under `static/vendor/stockfish/`) as a Web Worker communicating over
the UCI protocol via `postMessage`. It supports two evaluation modes:

- **Single-line** (`evaluate`): fires an `EvalCallback` at each search depth.
- **MultiPV** (`evaluateMultiPV`): accumulates lines across multipv indices at
  each depth, then fires a `MultiPVCallback` with the full set.

MultiPV is the default -- initialized with `setoption name MultiPV value 5`
during the UCI handshake. The eval bar visual is a 24px-wide vertical bar
between the coaching panel and the board. White's portion grows from the
bottom, Black's from the top. A sigmoid maps eval to the split-point
percentage: `50 + 50 * (2 / (1 + exp(-cp / 300)) - 1)`. Mate scores pin to
0% or 100%.

The eval bar fades in (opacity transition, 0.4s) when coaching first fires --
hidden until then so the initial board view stays uncluttered. A monospace
label at the top shows the numeric evaluation (+1.3, M4, etc.).

### Coaching Panel (left column in `main.ts`)

The coaching panel is a scrolling column of message bubbles. Each message has a
severity class -- `brilliant`, `inaccuracy`, `mistake`, or `blunder` -- that
controls its left border color and tinted background:

| Severity    | Border color | Background tint           |
|-------------|-------------|---------------------------|
| Brilliant   | `#4ade80`   | `rgba(74, 222, 128, 0.1)` |
| Inaccuracy  | `#fbbf24`   | `rgba(251, 191, 36, 0.1)` |
| Mistake     | `#fb923c`   | `rgba(251, 146, 60, 0.1)` |
| Blunder     | `#f87171`   | `rgba(248, 113, 113, 0.1)`|

Clicking a message jumps the board to that ply via
`GameController.jumpToPly()`, turning the coaching panel into a navigable
game log.

Debug bubbles (collapsible `<details>` elements) can appear above coaching
messages, showing the grounded prompt sent to the LLM. These use 10px
monospace in a dark inset (`#0f1729`) and collapse by default.

The panel label ("Coach") uses the small-caps style shared across all section
labels.

### Hamburger Menu (header, built in `main.ts`)

An absolutely-positioned dropdown anchored to the header's right edge.
Contains:

1. **New Game** button -- calls `GameController.newGame()` and resets all UI
   state.
2. **Skill Level** selector -- a `<select>` with five ELO profile options
   (Beginner 600-800 through Competitive 1400+). Changing the selection
   starts a new game at the chosen level immediately via
   `GameController.setEloProfile()`.
3. **FEN input** -- monospace text field. On change, validates the FEN via
   `GameController.setPosition()`. Invalid FEN flashes the border red for 1.5
   seconds.
4. **Keyboard shortcut reference** -- arrow keys for move navigation, Home/End
   for first/last, `n` for new game. Displayed in 11px monospace with `<kbd>`
   styling.

The menu opens on hamburger button click and closes on any click outside.
Click events inside the menu stop propagating so interactions with the select
and input never dismiss the dropdown.

### Right Panel: Analysis and Move List

The right panel is a vertical flex column containing:

- **Game status** -- checkmate/stalemate/draw results. Green by default,
  red on game end.
- **Analysis section** -- eval display (e.g. "Eval: +0.35 (depth 18)") and
  MultiPV lines. The top PV line is bold white; subsequent lines are muted.
  Each line shows a fixed-width score span followed by SAN notation (converted
  from UCI by `GameController.uciToSan()`).
- **Move list** -- a CSS grid with three columns: move number (32px), white
  move, black move. Alternating row backgrounds (#0f1729 / #111d35). Clicking
  a move jumps to that ply. The active ply gets a green-tinted background
  (`rgba(74, 222, 128, 0.15)`). The list auto-scrolls to the bottom on new
  moves.
- **Viewing indicator** -- appears when navigating away from the latest
  position (e.g. "Viewing move 12 of 34"). Monospace, yellow (#fbbf24).


## Board Annotations

Coaching data from the server includes two annotation types:

- **Arrows** -- drawn between two squares with a named brush (green or red).
  Mapped to chessground's `DrawShape` with `orig` and `dest`.
- **Square highlights** -- a single square with a brush. Mapped to `DrawShape`
  with only `orig`.

`board.setAutoShapes()` renders both as SVG overlays on the chessground board.
The shapes layer sits at z-index 2 (above the board, below dragged pieces at
z-index 11).

Color semantics are simple: **green** marks strength (the move to play, a
strong square, a tactical opportunity). **Red** marks danger (a threat, a
weakness, a hanging piece). The coach aims for one or two annotations per
coaching moment -- enough to focus attention without overwhelming.

`clearCoaching()` removes shapes when the student makes the next move. During
history navigation, shapes reappear for plies that have stored coaching data
(`coachingByPly` map in GameController).


## Frontend Technology Stack

| Dependency   | Version | Role                                     | Size   |
|-------------|---------|------------------------------------------|--------|
| chessground | 9.x     | Board rendering, drag interaction        | ~30KB  |
| chess.js    | 1.4.x   | Client-side move validation, SAN/FEN     | ~25KB  |
| stockfish   | 18.0.5  | Browser evaluation (WASM Web Worker)     | ~7MB   |
| snabbdom    | 3.x     | Virtual DOM (available, not yet primary)  | ~3KB   |
| esbuild     | 0.25.x  | Bundler (dev dependency)                 | -      |
| TypeScript  | 5.x     | Type checking (dev dependency)           | -      |

**Why no framework?** The UI has roughly a dozen DOM elements that change.
Chessground manages the board entirely. The eval bar is three divs. The move
list rebuilds its grid on each move. The coaching panel appends messages. For
this level of DOM manipulation, `document.createElement` suffices and adds zero
runtime overhead. Snabbdom sits in the dependency list for future use if the
interface grows more dynamic, but at ~3KB it is a thin virtual DOM diff layer,
not a framework.

**esbuild** bundles `main.ts` and all imports into a single `static/app.js`
ESM file. Build time measures in milliseconds. The build script also
concatenates chessground's CSS assets into `static/chessground.css`. No CSS
preprocessor, no PostCSS, no minification step beyond esbuild's default. App
styles live inline in `index.html`; board and piece styles live in
`chessground.css`.


## Chessground Integration

Chessground is the board rendering library from the Lichess project. It owns a
self-contained DOM subtree inside the `.board-wrap` container and manages its
own event handling for piece dragging, click-to-move, and animation.

Key integration points:

- **Legal moves** -- `GameController.syncBoard()` computes a `Map<Key, Key[]>`
  of legal destinations from chess.js and passes it to chessground via
  `movable.dests`. This enables the legal-move dots (green radial gradients on
  valid destination squares).
- **After-move callback** -- chessground fires the `after` callback when a
  piece drops. `GameController.handleMove()` then validates the move, sends it
  to the server, and applies the opponent's response.
- **Promotion** -- detected when a pawn reaches the 8th (or 1st) rank. A
  full-screen overlay with four piece buttons (queen, rook, bishop, knight)
  appears. The selected piece appends to the UCI string before sending to
  the server.
- **Piece assets** -- cburnett SVGs (the standard Lichess piece set),
  base64-encoded as `background-image` data URIs in `chessground.css`. Each of
  the 12 piece types (6 per color) has its own CSS rule under
  `.cg-wrap piece.{type}.{color}`. No external image requests.
- **Board colors** -- overridden from chessground's default brown theme to a
  cool blue-gray. The dark squares use `#546e7a` at 25% opacity over an
  `#8ca2ad` base, applied as an inline SVG `background-image` on `cg-board`.
- **Auto-shapes** -- `board.setAutoShapes()` renders coaching arrows and
  highlights as SVG elements in a dedicated overlay layer within the
  chessground DOM.


## Game State and Navigation

`GameController` in `game.ts` coordinates all state. It owns:

- A `Chess` instance (from chess.js) holding the canonical game state.
- The chessground `Api` for board updates.
- A `BrowserEngine` for local evaluation.
- A server session ID for the game API.
- A `coachingByPly` map storing coaching data keyed by ply number.

Navigation (arrow keys, move list clicks, Home/End) calls `jumpToPly()`, which
replays move history up to the target ply in a temporary `Chess` instance,
syncs the board to that position, restores any coaching shapes for that ply,
and triggers a fresh browser engine evaluation. When navigating away from the
latest position, the board becomes read-only (no legal moves shown) and a
viewing indicator appears.

The callback system uses registration: `main.ts` sets callbacks on
GameController for move list updates, MultiPV eval, promotion prompts, game
status, coaching display, and ply changes. This keeps GameController free of
DOM knowledge -- it communicates through typed callback interfaces.


## Responsive Considerations

The current layout targets desktop. The board sizes to fill vertical viewport
space, and the flanking panels share remaining horizontal space equally. On
viewports narrower than about 1200px, panels compress and content truncates
(PV lines use `text-overflow: ellipsis`, the coaching panel scrolls).

No mobile layout exists yet. The grid does not reflow to a stacked arrangement
on narrow screens. Chessground supports touch interaction natively, so the
board itself would work on mobile -- the challenge is fitting the panels. A
future responsive pass would likely stack the board above a tabbed panel
(coach / moves / analysis) on narrow viewports.


## COEP/COOP Headers

Stockfish WASM runs in a Web Worker and benefits from `SharedArrayBuffer` for
its internal threading. Browsers require two HTTP headers to enable
`SharedArrayBuffer`:

```
Cross-Origin-Embedder-Policy: require-corp
Cross-Origin-Opener-Policy: same-origin
```

FastAPI middleware applies these headers on all responses. Without them, the
stockfish Worker falls back to single-threaded execution (the vendored build is
the lite single-threaded variant, so this is the expected mode, but the headers
keep the option open for a multi-threaded build later).

These headers carry a side effect: all cross-origin resources (images, scripts,
fonts) must either be same-origin or served with appropriate CORS headers.
Since all assets (JS bundle, CSS, piece SVGs, stockfish WASM) ship from the
same FastAPI static file handler, the constraint holds without additional
configuration.
