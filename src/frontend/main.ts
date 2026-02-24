import { createBoard } from "./board";
import { BrowserEngine, MultiPVInfo } from "./eval";
import { GameController, PromotionPiece } from "./game";
import { CoachingData } from "./api";

function init() {
  const root = document.getElementById("app");
  if (!root) return;

  // --- Header ---
  const header = document.createElement("header");
  header.className = "app-header";
  root.appendChild(header);

  const title = document.createElement("h1");
  title.textContent = "Chess Teacher";
  header.appendChild(title);

  const hamburgerBtn = document.createElement("button");
  hamburgerBtn.className = "hamburger-btn";
  hamburgerBtn.setAttribute("aria-label", "Menu");
  for (let i = 0; i < 3; i++) {
    hamburgerBtn.appendChild(document.createElement("span"));
  }
  header.appendChild(hamburgerBtn);

  // Hamburger menu dropdown
  const hamburgerMenu = document.createElement("div");
  hamburgerMenu.className = "hamburger-menu";
  header.appendChild(hamburgerMenu);

  const menuFenInput = document.createElement("input");
  menuFenInput.type = "text";
  menuFenInput.placeholder = "Load FEN\u2026";
  menuFenInput.className = "fen-input";
  hamburgerMenu.appendChild(menuFenInput);

  const shortcutsRef = document.createElement("div");
  shortcutsRef.className = "shortcuts-ref";
  shortcutsRef.innerHTML =
    "<kbd>\u2190</kbd> <kbd>\u2192</kbd> navigate moves<br>" +
    "<kbd>\u2191</kbd> <kbd>\u2193</kbd> <kbd>Home</kbd> <kbd>End</kbd> first / last<br>" +
    "<kbd>n</kbd> new game";
  hamburgerMenu.appendChild(shortcutsRef);

  hamburgerBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    hamburgerMenu.classList.toggle("open");
  });
  document.addEventListener("click", () => {
    hamburgerMenu.classList.remove("open");
  });
  hamburgerMenu.addEventListener("click", (e) => {
    e.stopPropagation();
  });

  // --- Layout wrapper (centers the grid vertically) ---
  const layoutWrap = document.createElement("div");
  layoutWrap.className = "layout-wrap";
  root.appendChild(layoutWrap);

  // --- Layout grid ---
  const layout = document.createElement("div");
  layout.className = "layout";
  layoutWrap.appendChild(layout);

  // 1. Coach column (left)
  const coachColumn = document.createElement("div");
  coachColumn.className = "coach-column";
  layout.appendChild(coachColumn);

  const coachLabel = document.createElement("div");
  coachLabel.className = "coach-column-label";
  coachLabel.textContent = "Coach";
  coachColumn.appendChild(coachLabel);

  const coachMessages = document.createElement("div");
  coachMessages.className = "coach-messages";
  coachColumn.appendChild(coachMessages);

  // 2. Eval bar
  const evalBarWrap = document.createElement("div");
  evalBarWrap.className = "eval-bar-wrap";
  layout.appendChild(evalBarWrap);

  const evalBarBlack = document.createElement("div");
  evalBarBlack.className = "eval-bar-black";
  evalBarBlack.style.height = "50%";
  evalBarWrap.appendChild(evalBarBlack);

  const evalBarWhite = document.createElement("div");
  evalBarWhite.className = "eval-bar-white";
  evalBarWhite.style.height = "50%";
  evalBarWrap.appendChild(evalBarWhite);

  const evalBarLabel = document.createElement("div");
  evalBarLabel.className = "eval-bar-label";
  evalBarLabel.textContent = "0.0";
  evalBarWrap.appendChild(evalBarLabel);

  // 3. Board
  const boardWrap = document.createElement("div");
  boardWrap.className = "board-wrap";
  layout.appendChild(boardWrap);

  // 4. Right panel
  const rightPanel = document.createElement("div");
  rightPanel.className = "right-panel";
  layout.appendChild(rightPanel);

  // New Game button
  const newGameBtn = document.createElement("button");
  newGameBtn.className = "new-game-btn";
  newGameBtn.textContent = "New Game";
  rightPanel.appendChild(newGameBtn);

  // Skill Level
  const skillLevelLabel = document.createElement("div");
  skillLevelLabel.className = "section-label";
  skillLevelLabel.textContent = "Skill Level";
  rightPanel.appendChild(skillLevelLabel);

  const eloSelect = document.createElement("select");
  eloSelect.className = "elo-select-main";
  const eloOptions: [string, string][] = [
    ["beginner", "Beginner (600-800)"],
    ["intermediate", "Intermediate (800-1000)"],
    ["advancing", "Advancing (1000-1200)"],
    ["club", "Club (1200-1400)"],
    ["competitive", "Competitive (1400+)"],
  ];
  for (const [value, label] of eloOptions) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    if (value === "intermediate") opt.selected = true;
    eloSelect.appendChild(opt);
  }
  rightPanel.appendChild(eloSelect);

  // Game status
  const statusDisplay = document.createElement("div");
  statusDisplay.className = "game-status";
  rightPanel.appendChild(statusDisplay);

  // Analysis section label
  const analysisLabel = document.createElement("div");
  analysisLabel.className = "section-label";
  analysisLabel.textContent = "Analysis";
  rightPanel.appendChild(analysisLabel);

  // Eval display
  const evalDisplay = document.createElement("div");
  evalDisplay.className = "eval-display";
  evalDisplay.textContent = "Eval: \u2014";
  rightPanel.appendChild(evalDisplay);

  // MultiPV line display
  const lineDisplay = document.createElement("div");
  lineDisplay.className = "line-display";
  lineDisplay.textContent = "Lines: \u2014";
  rightPanel.appendChild(lineDisplay);

  // Moves section label
  const movesLabel = document.createElement("div");
  movesLabel.className = "section-label";
  movesLabel.textContent = "Moves";
  rightPanel.appendChild(movesLabel);

  // Move history
  const moveHistory = document.createElement("div");
  moveHistory.className = "move-history";
  rightPanel.appendChild(moveHistory);

  // Viewing indicator
  const viewingIndicator = document.createElement("div");
  viewingIndicator.className = "viewing-indicator";
  rightPanel.appendChild(viewingIndicator);

  // FEN display (click to copy)
  const fenDisplay = document.createElement("input");
  fenDisplay.type = "text";
  fenDisplay.readOnly = true;
  fenDisplay.className = "fen-display";
  fenDisplay.placeholder = "Position FEN";
  fenDisplay.title = "Click to copy FEN";
  rightPanel.appendChild(fenDisplay);

  function updateFenDisplay(fen: string) {
    fenDisplay.value = fen;
  }

  fenDisplay.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(fenDisplay.value);
      const originalBorder = fenDisplay.style.borderColor;
      fenDisplay.style.borderColor = "#4ade80";
      setTimeout(() => {
        fenDisplay.style.borderColor = originalBorder;
      }, 300);
    } catch (err) {
      // Fallback for older browsers
      fenDisplay.select();
      document.execCommand("copy");
    }
  });

  // --- Footer ---
  const footer = document.createElement("footer");
  footer.className = "app-footer";
  root.appendChild(footer);

  const engineStatus = document.createElement("span");
  engineStatus.className = "engine-status";
  engineStatus.textContent = "Engine: loading";
  footer.appendChild(engineStatus);

  // --- Promotion UI ---
  function showPromotionChooser(
    isWhite: boolean,
  ): Promise<PromotionPiece> {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "promotion-overlay";

      const choices = document.createElement("div");
      choices.className = "promotion-choices";
      overlay.appendChild(choices);

      const pieces: { piece: PromotionPiece; symbol: string }[] = isWhite
        ? [
            { piece: "q", symbol: "\u2655" },
            { piece: "r", symbol: "\u2656" },
            { piece: "b", symbol: "\u2657" },
            { piece: "n", symbol: "\u2658" },
          ]
        : [
            { piece: "q", symbol: "\u265B" },
            { piece: "r", symbol: "\u265C" },
            { piece: "b", symbol: "\u265D" },
            { piece: "n", symbol: "\u265E" },
          ];

      for (const { piece, symbol } of pieces) {
        const btn = document.createElement("button");
        btn.textContent = symbol;
        btn.addEventListener("click", () => {
          overlay.remove();
          resolve(piece);
        });
        choices.appendChild(btn);
      }

      document.body.appendChild(overlay);
    });
  }

  // --- Eval bar update ---
  function updateEvalBar(scoreCp: number | null, scoreMate: number | null) {
    let whitePct: number;
    let label: string;

    if (scoreMate !== null) {
      whitePct = scoreMate > 0 ? 100 : 0;
      label = `M${Math.abs(scoreMate)}`;
    } else if (scoreCp !== null) {
      whitePct = 50 + 50 * (2 / (1 + Math.exp(-scoreCp / 300)) - 1);
      const score = scoreCp / 100;
      label = `${score > 0 ? "+" : ""}${score.toFixed(1)}`;
    } else {
      whitePct = 50;
      label = "0.0";
    }

    evalBarWhite.style.height = `${whitePct}%`;
    evalBarBlack.style.height = `${100 - whitePct}%`;
    evalBarLabel.textContent = label;
  }

  // --- MultiPV display ---
  function updateMultiEval(info: MultiPVInfo) {
    const line1 = info.lines[0];
    if (line1) {
      if (line1.scoreCp !== null) {
        const score = (line1.scoreCp / 100).toFixed(2);
        evalDisplay.textContent = `Eval: ${line1.scoreCp > 0 ? "+" : ""}${score} (depth ${info.depth})`;
      } else if (line1.scoreMate !== null) {
        evalDisplay.textContent = `Mate in ${Math.abs(line1.scoreMate)} (depth ${info.depth})`;
      }
      updateEvalBar(line1.scoreCp, line1.scoreMate);
    }

    lineDisplay.innerHTML = "";
    for (const line of info.lines) {
      const div = document.createElement("div");
      div.className = "pv-line";

      const scoreSpan = document.createElement("span");
      scoreSpan.className = "pv-score";
      if (line.scoreMate !== null) {
        scoreSpan.textContent = `M${Math.abs(line.scoreMate)}`;
      } else if (line.scoreCp !== null) {
        const s = (line.scoreCp / 100).toFixed(1);
        scoreSpan.textContent = `${line.scoreCp > 0 ? "+" : ""}${s}`;
      }
      div.appendChild(scoreSpan);

      const san = gc.uciToSan(line.pv.slice(0, 6));
      div.appendChild(document.createTextNode(san.join(" ")));

      lineDisplay.appendChild(div);
    }
  }

  // --- Move history rendering (grid) ---
  function renderMoveList(moves: string[]) {
    moveHistory.innerHTML = "";
    const activePly = gc.getCurrentPly();
    for (let i = 0; i < moves.length; i += 2) {
      const row = document.createElement("div");
      row.className = "move-row";

      const numEl = document.createElement("span");
      numEl.className = "move-number";
      numEl.textContent = `${Math.floor(i / 2) + 1}.`;
      row.appendChild(numEl);

      // White move
      const whitePly = i + 1;
      const whiteEl = document.createElement("span");
      whiteEl.className = "move";
      if (whitePly === activePly) whiteEl.classList.add("active");
      whiteEl.textContent = moves[i];
      whiteEl.addEventListener("click", () => gc.jumpToPly(whitePly));
      row.appendChild(whiteEl);

      // Black move (or empty cell)
      if (i + 1 < moves.length) {
        const blackPly = i + 2;
        const blackEl = document.createElement("span");
        blackEl.className = "move";
        if (blackPly === activePly) blackEl.classList.add("active");
        blackEl.textContent = moves[i + 1];
        blackEl.addEventListener("click", () => gc.jumpToPly(blackPly));
        row.appendChild(blackEl);
      } else {
        row.appendChild(document.createElement("span"));
      }

      moveHistory.appendChild(row);
    }
    moveHistory.scrollTop = moveHistory.scrollHeight;

    // Update FEN display
    updateFenDisplay(gc.fen());
  }

  // --- Ply change handler ---
  function onPlyChange(ply: number, maxPly: number) {
    const moveSpans = moveHistory.querySelectorAll(".move");
    moveSpans.forEach((span) => {
      const el = span as HTMLElement;
      if (el.dataset.ply === String(ply)) {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    });

    const activeEl = moveHistory.querySelector(".move.active");
    if (activeEl) {
      activeEl.scrollIntoView({ block: "nearest" });
    }

    if (ply < maxPly) {
      viewingIndicator.textContent = `Viewing move ${ply} of ${maxPly}`;
      boardWrap.classList.add("viewing-history");
    } else {
      viewingIndicator.textContent = "";
      boardWrap.classList.remove("viewing-history");
    }

    // Update FEN display
    updateFenDisplay(gc.fen());
  }

  // --- Coaching display ---
  function showCoaching(coaching: CoachingData) {
    // Debug: log the grounded prompt to console
    if (coaching.debug_prompt) {
      console.group(`%c[Coach Prompt] ply ${gc.getCurrentPly()}`, "color: #4ade80; font-weight: bold");
      console.log(coaching.debug_prompt);
      console.groupEnd();
    }

    // Collapsible debug bubble showing the prompt sent to LLM
    if (coaching.debug_prompt) {
      const debugBubble = document.createElement("details");
      debugBubble.className = "coach-debug";
      const summary = document.createElement("summary");
      summary.textContent = "LLM prompt";
      debugBubble.appendChild(summary);
      const pre = document.createElement("pre");
      pre.textContent = coaching.debug_prompt;
      debugBubble.appendChild(pre);
      coachMessages.appendChild(debugBubble);
    }

    const msg = document.createElement("div");
    msg.className = `coach-message ${coaching.quality}`;
    msg.textContent = coaching.message;
    msg.dataset.ply = String(gc.getCurrentPly());
    msg.addEventListener("click", () => {
      const ply = parseInt(msg.dataset.ply!, 10);
      gc.jumpToPly(ply);
    });
    coachMessages.appendChild(msg);
    coachMessages.scrollTop = coachMessages.scrollHeight;

    // Show eval bar when coaching fires
    evalBarWrap.classList.add("visible");
  }

  // --- Game status ---
  function showStatus(status: string, result: string | null) {
    if (status === "checkmate") {
      const winner = result === "1-0" ? "White" : "Black";
      statusDisplay.textContent = `Checkmate \u2014 ${winner} wins`;
    } else if (status === "stalemate") {
      statusDisplay.textContent = "Stalemate \u2014 Draw";
    } else if (status === "draw") {
      statusDisplay.textContent = "Draw";
    }
    statusDisplay.style.color = "#f87171";
  }

  // --- New game reset ---
  function resetUI() {
    gc.newGame().then(() => {
      statusDisplay.textContent = "";
      statusDisplay.style.color = "#4ade80";
      evalDisplay.textContent = "Eval: \u2014";
      lineDisplay.innerHTML = "";
      lineDisplay.textContent = "Lines: \u2014";
      coachMessages.innerHTML = "";
      viewingIndicator.textContent = "";
      updateEvalBar(null, null);
      evalBarWrap.classList.remove("visible");

      // Update FEN display
      updateFenDisplay(gc.fen());
    });
  }

  // --- Initialize ---
  const engine = new BrowserEngine();

  const board = createBoard(boardWrap, (orig, dest) => {
    gc.handleMove(orig, dest);
  });

  const gc = new GameController(board, engine);

  gc.setMoveListCallback(renderMoveList);
  gc.setMultiPVCallback(updateMultiEval);
  gc.setPromotionCallback((_orig, dest) => {
    const isWhite = dest[1] === "8";
    return showPromotionChooser(isWhite);
  });
  gc.setStatusCallback(showStatus);
  gc.setCoachingCallback(showCoaching);
  gc.setPlyChangeCallback(onPlyChange);

  // Create initial server session
  gc.newGame();

  // Keyboard navigation
  document.addEventListener("keydown", (e) => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

    switch (e.key) {
      case "ArrowLeft":
        e.preventDefault();
        gc.stepBack();
        break;
      case "ArrowRight":
        e.preventDefault();
        gc.stepForward();
        break;
      case "ArrowUp":
      case "Home":
        e.preventDefault();
        gc.jumpToPly(0);
        break;
      case "ArrowDown":
      case "End":
        e.preventDefault();
        gc.jumpToPly(gc.getMaxPly());
        break;
      case "n":
        e.preventDefault();
        resetUI();
        break;
    }
  });

  // New game button
  newGameBtn.addEventListener("click", () => {
    resetUI();
  });

  // ELO select
  eloSelect.addEventListener("change", () => {
    gc.setEloProfile(eloSelect.value);
    resetUI();
  });

  // Menu: FEN input
  menuFenInput.addEventListener("change", () => {
    const fen = menuFenInput.value.trim();
    if (fen) {
      const valid = gc.setPosition(fen);
      if (!valid) {
        menuFenInput.style.borderColor = "#f87171";
        setTimeout(() => { menuFenInput.style.borderColor = "#333"; }, 1500);
      } else {
        hamburgerMenu.classList.remove("open");
      }
    }
  });

  // Initialize browser engine
  engine
    .init("/static/vendor/stockfish/stockfish.js")
    .then(() => {
      engineStatus.textContent = "Engine: ready";
      engineStatus.classList.add("connected");
      engine.evaluateMultiPV(gc.fen(), updateMultiEval);
    })
    .catch((err) => {
      console.warn("Browser Stockfish unavailable:", err);
      evalDisplay.textContent = "Eval: (engine unavailable)";
      engineStatus.textContent = "Engine: unavailable";
      engineStatus.classList.add("error");
    });
}

document.addEventListener("DOMContentLoaded", init);
