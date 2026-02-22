import { createBoard } from "./board";
import { BrowserEngine, MultiPVInfo } from "./eval";
import { GameController, PromotionPiece } from "./game";
import { CoachingData } from "./api";

function init() {
  const root = document.getElementById("app");
  if (!root) return;

  // --- Layout ---
  const layout = document.createElement("div");
  layout.className = "layout";
  root.appendChild(layout);

  // Board
  const boardWrap = document.createElement("div");
  boardWrap.className = "board-wrap";
  layout.appendChild(boardWrap);

  // Eval bar
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

  // Right panel
  const panel = document.createElement("div");
  panel.className = "panel";
  layout.appendChild(panel);

  // Game status
  const statusDisplay = document.createElement("div");
  statusDisplay.className = "game-status";
  panel.appendChild(statusDisplay);

  // Eval display
  const evalDisplay = document.createElement("div");
  evalDisplay.className = "eval-display";
  evalDisplay.textContent = "Eval: \u2014";
  panel.appendChild(evalDisplay);

  // MultiPV line display
  const lineDisplay = document.createElement("div");
  lineDisplay.className = "line-display";
  lineDisplay.textContent = "Lines: \u2014";
  panel.appendChild(lineDisplay);

  // Coach panel
  const coachPanel = document.createElement("div");
  coachPanel.className = "coach-panel";
  panel.appendChild(coachPanel);

  // Viewing indicator
  const viewingIndicator = document.createElement("div");
  viewingIndicator.className = "viewing-indicator";
  panel.appendChild(viewingIndicator);

  // Move history
  const moveHistory = document.createElement("div");
  moveHistory.className = "move-history";
  panel.appendChild(moveHistory);

  // Nav controls
  const navControls = document.createElement("div");
  navControls.className = "nav-controls";
  panel.appendChild(navControls);

  const navBackBtn = document.createElement("button");
  navBackBtn.textContent = "\u25C0";
  navControls.appendChild(navBackBtn);

  const navForwardBtn = document.createElement("button");
  navForwardBtn.textContent = "\u25B6";
  navControls.appendChild(navForwardBtn);

  // Controls
  const controls = document.createElement("div");
  controls.className = "controls";
  panel.appendChild(controls);

  const newGameBtn = document.createElement("button");
  newGameBtn.textContent = "New Game";
  controls.appendChild(newGameBtn);

  // Engine status (text label replaces old status dot)
  const engineStatus = document.createElement("div");
  engineStatus.className = "engine-status";
  engineStatus.textContent = "Engine: loading";
  panel.appendChild(engineStatus);

  // FEN input below layout
  const fenInput = document.createElement("input");
  fenInput.type = "text";
  fenInput.placeholder = "Enter FEN to analyze a position\u2026";
  fenInput.className = "fen-input";
  root.appendChild(fenInput);

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
      // Sigmoid mapping: 50 + 50 * (2 / (1 + e^(-cp/300)) - 1)
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
    // Update header eval from line 1
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

    // Render all PV lines
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

  // --- Move history rendering ---
  function renderMoveList(moves: string[]) {
    moveHistory.innerHTML = "";
    const activePly = gc.getCurrentPly();
    for (let i = 0; i < moves.length; i += 2) {
      const moveNum = Math.floor(i / 2) + 1;
      const numSpan = document.createElement("span");
      numSpan.className = "move-number";
      numSpan.textContent = `${moveNum}.`;
      moveHistory.appendChild(numSpan);

      const whitePly = i + 1; // ply is 1-indexed (move i is ply i+1)
      const whiteSpan = document.createElement("span");
      whiteSpan.className = "move";
      if (whitePly === activePly) whiteSpan.classList.add("active");
      whiteSpan.textContent = moves[i];
      whiteSpan.dataset.ply = String(whitePly);
      whiteSpan.addEventListener("click", () => {
        gc.jumpToPly(whitePly);
      });
      moveHistory.appendChild(whiteSpan);

      if (i + 1 < moves.length) {
        const blackPly = i + 2;
        const blackSpan = document.createElement("span");
        blackSpan.className = "move";
        if (blackPly === activePly) blackSpan.classList.add("active");
        blackSpan.textContent = moves[i + 1];
        blackSpan.dataset.ply = String(blackPly);
        blackSpan.addEventListener("click", () => {
          gc.jumpToPly(blackPly);
        });
        moveHistory.appendChild(blackSpan);
      }
    }
    // Scroll to bottom
    moveHistory.scrollTop = moveHistory.scrollHeight;
  }

  // --- Ply change handler ---
  function onPlyChange(ply: number, maxPly: number) {
    // Update active highlighting in move list
    const moveSpans = moveHistory.querySelectorAll(".move");
    moveSpans.forEach((span) => {
      const el = span as HTMLElement;
      if (el.dataset.ply === String(ply)) {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    });

    // Scroll active move into view
    const activeEl = moveHistory.querySelector(".move.active");
    if (activeEl) {
      activeEl.scrollIntoView({ block: "nearest" });
    }

    // Viewing indicator
    if (ply < maxPly) {
      viewingIndicator.textContent = `Viewing move ${ply} of ${maxPly}`;
    } else {
      viewingIndicator.textContent = "";
    }
  }

  // --- Coaching display ---
  function showCoaching(coaching: CoachingData) {
    const msg = document.createElement("div");
    msg.className = `coach-message ${coaching.quality}`;
    msg.textContent = coaching.message;
    msg.dataset.ply = String(gc.getCurrentPly());
    msg.addEventListener("click", () => {
      const ply = parseInt(msg.dataset.ply!, 10);
      gc.jumpToPly(ply);
    });
    coachPanel.appendChild(msg);
    coachPanel.scrollTop = coachPanel.scrollHeight;
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

  // Nav button handlers
  navBackBtn.addEventListener("click", () => gc.stepBack());
  navForwardBtn.addEventListener("click", () => gc.stepForward());

  // Keyboard navigation
  document.addEventListener("keydown", (e) => {
    // Don't intercept when typing in input fields
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
      case "Home":
        e.preventDefault();
        gc.jumpToPly(0);
        break;
      case "End":
        e.preventDefault();
        gc.jumpToPly(gc.getMaxPly());
        break;
    }
  });

  // New game button
  newGameBtn.addEventListener("click", () => {
    gc.newGame().then(() => {
      statusDisplay.textContent = "";
      statusDisplay.style.color = "#4ade80";
      evalDisplay.textContent = "Eval: \u2014";
      lineDisplay.innerHTML = "";
      lineDisplay.textContent = "Lines: \u2014";
      coachPanel.innerHTML = "";
      viewingIndicator.textContent = "";
      updateEvalBar(null, null);
    });
  });

  // FEN input
  fenInput.addEventListener("change", () => {
    const fen = fenInput.value.trim();
    if (fen) {
      const valid = gc.setPosition(fen);
      if (!valid) {
        fenInput.style.borderColor = "#f87171";
        setTimeout(() => { fenInput.style.borderColor = "#333"; }, 1500);
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
