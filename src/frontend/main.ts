import { createBoard } from "./board";
import { BrowserEngine, EvalInfo } from "./eval";
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

  // Best line display
  const lineDisplay = document.createElement("div");
  lineDisplay.className = "line-display";
  lineDisplay.textContent = "Best line: \u2014";
  panel.appendChild(lineDisplay);

  // Coach panel
  const coachPanel = document.createElement("div");
  coachPanel.className = "coach-panel";
  panel.appendChild(coachPanel);

  // Move history
  const moveHistory = document.createElement("div");
  moveHistory.className = "move-history";
  panel.appendChild(moveHistory);

  // Controls
  const controls = document.createElement("div");
  controls.className = "controls";
  panel.appendChild(controls);

  const newGameBtn = document.createElement("button");
  newGameBtn.textContent = "New Game";
  controls.appendChild(newGameBtn);

  // Engine status
  const statusDot = document.createElement("div");
  statusDot.className = "status-dot";
  panel.appendChild(statusDot);

  // FEN input below layout
  const fenInput = document.createElement("input");
  fenInput.type = "text";
  fenInput.placeholder = "Paste FEN...";
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

  // --- Eval display ---
  function updateEval(info: EvalInfo) {
    if (info.scoreCp !== null) {
      const score = (info.scoreCp / 100).toFixed(2);
      evalDisplay.textContent = `Eval: ${info.scoreCp > 0 ? "+" : ""}${score} (depth ${info.depth})`;
    } else if (info.scoreMate !== null) {
      evalDisplay.textContent = `Mate in ${Math.abs(info.scoreMate)} (depth ${info.depth})`;
    }
    if (info.pv.length > 0) {
      const san = gc.uciToSan(info.pv.slice(0, 5));
      lineDisplay.textContent = `Best: ${san.join(" ")}`;
    }
  }

  // --- Move history rendering ---
  function renderMoveList(moves: string[]) {
    moveHistory.innerHTML = "";
    for (let i = 0; i < moves.length; i += 2) {
      const moveNum = Math.floor(i / 2) + 1;
      const numSpan = document.createElement("span");
      numSpan.className = "move-number";
      numSpan.textContent = `${moveNum}.`;
      moveHistory.appendChild(numSpan);

      const whiteSpan = document.createElement("span");
      whiteSpan.className = "move";
      whiteSpan.textContent = moves[i];
      moveHistory.appendChild(whiteSpan);

      if (i + 1 < moves.length) {
        const blackSpan = document.createElement("span");
        blackSpan.className = "move";
        blackSpan.textContent = moves[i + 1];
        moveHistory.appendChild(blackSpan);
      }
    }
    // Scroll to bottom
    moveHistory.scrollTop = moveHistory.scrollHeight;
  }

  // --- Coaching display ---
  function showCoaching(coaching: CoachingData) {
    const msg = document.createElement("div");
    msg.className = `coach-message ${coaching.quality}`;
    msg.textContent = coaching.message;
    coachPanel.appendChild(msg);
    coachPanel.scrollTop = coachPanel.scrollHeight;
  }

  // --- Game status ---
  function showStatus(status: string, result: string | null) {
    if (status === "checkmate") {
      const winner = result === "1-0" ? "White" : "Black";
      statusDisplay.textContent = `Checkmate — ${winner} wins`;
    } else if (status === "stalemate") {
      statusDisplay.textContent = "Stalemate — Draw";
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
  gc.setEvalCallback(updateEval);
  gc.setPromotionCallback((_orig, dest) => {
    const isWhite = dest[1] === "8";
    return showPromotionChooser(isWhite);
  });
  gc.setStatusCallback(showStatus);
  gc.setCoachingCallback(showCoaching);

  // Create initial server session
  gc.newGame();

  // New game button
  newGameBtn.addEventListener("click", () => {
    gc.newGame().then(() => {
      statusDisplay.textContent = "";
      statusDisplay.style.color = "#4ade80";
      evalDisplay.textContent = "Eval: \u2014";
      lineDisplay.textContent = "Best line: \u2014";
      coachPanel.innerHTML = "";
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
      statusDot.classList.add("connected");
      engine.evaluate(gc.fen(), updateEval);
    })
    .catch((err) => {
      console.warn("Browser Stockfish unavailable:", err);
      evalDisplay.textContent = "Eval: (engine unavailable)";
      statusDot.classList.add("error");
    });
}

document.addEventListener("DOMContentLoaded", init);
