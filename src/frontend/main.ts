import { createBoard } from "./board";
import { BrowserEngine, EvalInfo } from "./eval";

function init() {
  const root = document.getElementById("app");
  if (!root) return;

  // Layout: board + panel side by side
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

  // Status indicator
  const statusDot = document.createElement("div");
  statusDot.className = "status-dot";
  panel.appendChild(statusDot);

  // FEN input below layout
  const fenInput = document.createElement("input");
  fenInput.type = "text";
  fenInput.placeholder = "Paste FEN...";
  fenInput.className = "fen-input";
  root.appendChild(fenInput);

  // Current FEN tracking
  let currentFen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

  // Board
  const board = createBoard(boardWrap);

  // Browser engine
  const engine = new BrowserEngine();

  function updateEval(info: EvalInfo) {
    if (info.scoreCp !== null) {
      const score = (info.scoreCp / 100).toFixed(2);
      evalDisplay.textContent = `Eval: ${info.scoreCp > 0 ? "+" : ""}${score} (depth ${info.depth})`;
    } else if (info.scoreMate !== null) {
      evalDisplay.textContent = `Mate in ${Math.abs(info.scoreMate)} (depth ${info.depth})`;
    }
    if (info.pv.length > 0) {
      lineDisplay.textContent = `Best: ${info.pv.slice(0, 5).join(" ")}`;
    }
  }

  // FEN input triggers board update + eval
  fenInput.addEventListener("change", () => {
    const fen = fenInput.value.trim();
    if (fen) {
      currentFen = fen;
      board.set({ fen });
      engine.evaluate(fen, updateEval);
    }
  });

  // Initialize browser engine
  engine.init("/static/vendor/stockfish/stockfish.js")
    .then(() => {
      statusDot.classList.add("connected");
      // Evaluate starting position
      engine.evaluate(currentFen, updateEval);
    })
    .catch((err) => {
      console.warn("Browser Stockfish unavailable:", err);
      evalDisplay.textContent = "Eval: (engine unavailable)";
      statusDot.classList.add("error");
    });
}

document.addEventListener("DOMContentLoaded", init);
