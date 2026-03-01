import { createBoard } from "./board";
import { BrowserEngine, MultiPVInfo } from "./eval";
import { GameController, PromotionPiece } from "./game";
import { CoachingData } from "./api";
import { RemoteUCI } from "./remote";

/** Generate a chessground-compatible board SVG with the given square colors. */
function makeBoardSvg(lightHex: string, darkHex: string): string {
  // SVG checkerboard: 8x8 grid, light squares = background, dark squares = fill
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8" shape-rendering="crispEdges">
<rect width="8" height="8" fill="${lightHex}"/>
<g fill="${darkHex}">
<rect x="1" y="0" width="1" height="1"/><rect x="3" y="0" width="1" height="1"/><rect x="5" y="0" width="1" height="1"/><rect x="7" y="0" width="1" height="1"/>
<rect x="0" y="1" width="1" height="1"/><rect x="2" y="1" width="1" height="1"/><rect x="4" y="1" width="1" height="1"/><rect x="6" y="1" width="1" height="1"/>
<rect x="1" y="2" width="1" height="1"/><rect x="3" y="2" width="1" height="1"/><rect x="5" y="2" width="1" height="1"/><rect x="7" y="2" width="1" height="1"/>
<rect x="0" y="3" width="1" height="1"/><rect x="2" y="3" width="1" height="1"/><rect x="4" y="3" width="1" height="1"/><rect x="6" y="3" width="1" height="1"/>
<rect x="1" y="4" width="1" height="1"/><rect x="3" y="4" width="1" height="1"/><rect x="5" y="4" width="1" height="1"/><rect x="7" y="4" width="1" height="1"/>
<rect x="0" y="5" width="1" height="1"/><rect x="2" y="5" width="1" height="1"/><rect x="4" y="5" width="1" height="1"/><rect x="6" y="5" width="1" height="1"/>
<rect x="1" y="6" width="1" height="1"/><rect x="3" y="6" width="1" height="1"/><rect x="5" y="6" width="1" height="1"/><rect x="7" y="6" width="1" height="1"/>
<rect x="0" y="7" width="1" height="1"/><rect x="2" y="7" width="1" height="1"/><rect x="4" y="7" width="1" height="1"/><rect x="6" y="7" width="1" height="1"/>
</g>
</svg>`;
  return `url('data:image/svg+xml;base64,${btoa(svg)}')`;
}

function updateBoardColors() {
  const style = getComputedStyle(document.documentElement);
  const boardDark = style.getPropertyValue("--board-dark").trim();
  const boardLight = style.getPropertyValue("--board-light").trim();
  if (!boardDark || !boardLight) return;

  const cgBoard = document.querySelector("cg-board") as HTMLElement | null;
  if (cgBoard) {
    cgBoard.style.backgroundColor = boardLight;
    cgBoard.style.backgroundImage = makeBoardSvg(boardLight, boardDark);
  }
}

interface CustomTheme {
  label: string;
  mode: "dark" | "light";
  bg: {
    body: string; header: string; panel: string; input: string;
    button: string; buttonHover: string; rowOdd: string; rowEven: string;
  };
  border: { subtle: string; normal: string; strong: string };
  text: { primary: string; muted: string; dim: string; accent: string };
  board: { light: string; dark: string };
  lastUsed: number; // timestamp
}

const CUSTOM_THEMES_KEY = "chess-teacher-custom-themes";
const MAX_CUSTOM_THEMES = 5;

function loadCustomThemes(): CustomTheme[] {
  try {
    const raw = localStorage.getItem(CUSTOM_THEMES_KEY);
    if (!raw) return [];
    const themes = JSON.parse(raw) as CustomTheme[];
    // Sort by lastUsed descending (most recent first)
    return themes.sort((a, b) => b.lastUsed - a.lastUsed);
  } catch {
    return [];
  }
}

function saveCustomTheme(theme: CustomTheme): CustomTheme[] {
  let themes = loadCustomThemes();
  // Remove existing with same label (case-insensitive) to avoid duplicates
  themes = themes.filter(t => t.label.toLowerCase() !== theme.label.toLowerCase());
  themes.unshift(theme);
  // Evict oldest if over limit
  if (themes.length > MAX_CUSTOM_THEMES) {
    themes = themes.slice(0, MAX_CUSTOM_THEMES);
  }
  localStorage.setItem(CUSTOM_THEMES_KEY, JSON.stringify(themes));
  return themes;
}

function touchCustomTheme(label: string): void {
  const themes = loadCustomThemes();
  const theme = themes.find(t => t.label.toLowerCase() === label.toLowerCase());
  if (theme) {
    theme.lastUsed = Date.now();
    localStorage.setItem(CUSTOM_THEMES_KEY, JSON.stringify(
      themes.sort((a, b) => b.lastUsed - a.lastUsed)
    ));
  }
}

/** Dark-mode coaching severity variables */
const DARK_COACHING: Record<string, string> = {
  "--brilliant-bg": "rgba(74, 222, 128, 0.1)",
  "--brilliant-border": "#4ade80", "--brilliant-text": "#4ade80",
  "--inaccuracy-bg": "rgba(251, 191, 36, 0.1)",
  "--inaccuracy-border": "#fbbf24", "--inaccuracy-text": "#fbbf24",
  "--mistake-bg": "rgba(251, 146, 60, 0.1)",
  "--mistake-border": "#fb923c", "--mistake-text": "#fb923c",
  "--blunder-bg": "rgba(248, 113, 113, 0.1)",
  "--blunder-border": "#f87171", "--blunder-text": "#f87171",
  "--status-connected": "#4ade80", "--status-error": "#f87171", "--status-thinking": "#fbbf24",
};

/** Light-mode coaching severity variables */
const LIGHT_COACHING: Record<string, string> = {
  "--brilliant-bg": "rgba(22, 163, 74, 0.1)",
  "--brilliant-border": "#16a34a", "--brilliant-text": "#15803d",
  "--inaccuracy-bg": "rgba(202, 138, 4, 0.1)",
  "--inaccuracy-border": "#ca8a04", "--inaccuracy-text": "#a16207",
  "--mistake-bg": "rgba(234, 88, 12, 0.1)",
  "--mistake-border": "#ea580c", "--mistake-text": "#c2410c",
  "--blunder-bg": "rgba(220, 38, 38, 0.1)",
  "--blunder-border": "#dc2626", "--blunder-text": "#b91c1c",
  "--status-connected": "#15803d", "--status-error": "#dc2626", "--status-thinking": "#a16207",
};

function applyCustomTheme(theme: CustomTheme) {
  const root = document.documentElement;
  // Remove data-theme so built-in vars don't interfere
  root.removeAttribute("data-theme");

  const vars: Record<string, string> = {
    "--bg-body": theme.bg.body, "--bg-header": theme.bg.header,
    "--bg-panel": theme.bg.panel, "--bg-input": theme.bg.input,
    "--bg-button": theme.bg.button, "--bg-button-hover": theme.bg.buttonHover,
    "--bg-row-odd": theme.bg.rowOdd, "--bg-row-even": theme.bg.rowEven,
    "--border-subtle": theme.border.subtle, "--border": theme.border.normal,
    "--border-strong": theme.border.strong,
    "--text": theme.text.primary, "--text-muted": theme.text.muted,
    "--text-dim": theme.text.dim, "--accent": theme.text.accent,
    "--accent-glow": theme.text.accent.replace(/^#(..)(..)(..)$/, (_, r, g, b) =>
      `rgba(${parseInt(r, 16)}, ${parseInt(g, 16)}, ${parseInt(b, 16)}, 0.15)`),
    "--board-light": theme.board.light, "--board-dark": theme.board.dark,
    "--move-hover": theme.mode === "dark" ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.06)",
    "--move-active": theme.text.accent.replace(/^#(..)(..)(..)$/, (_, r, g, b) =>
      `rgba(${parseInt(r, 16)}, ${parseInt(g, 16)}, ${parseInt(b, 16)}, 0.15)`),
    "--debug-bg": theme.mode === "dark" ? "rgba(100,100,140,0.12)" : "rgba(80,80,100,0.08)",
    ...(theme.mode === "dark" ? DARK_COACHING : LIGHT_COACHING),
  };

  for (const [prop, val] of Object.entries(vars)) {
    root.style.setProperty(prop, val);
  }

  updateBoardColors();
}

function clearCustomThemeVars() {
  const root = document.documentElement;
  // Remove all inline CSS variables so data-theme takes over again
  root.removeAttribute("style");
}

function init() {
  const root = document.getElementById("app");
  if (!root) return;

  // Restore custom theme if previously selected
  const savedTheme = localStorage.getItem("chess-teacher-theme") || "dark";
  if (savedTheme.startsWith("custom:")) {
    const label = savedTheme.slice(7);
    const themes = loadCustomThemes();
    const theme = themes.find(t => t.label === label);
    if (theme) {
      // Will be applied after board is created (needs cg-board element)
      requestAnimationFrame(() => applyCustomTheme(theme));
    }
  }

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

  // Verbosity tabs
  const verbosityLabel = document.createElement("div");
  verbosityLabel.className = "menu-label";
  verbosityLabel.textContent = "coaching verbosity";
  hamburgerMenu.appendChild(verbosityLabel);

  const verbosityTabs = document.createElement("div");
  verbosityTabs.className = "verbosity-tabs";
  hamburgerMenu.appendChild(verbosityTabs);

  const savedVerbosity = localStorage.getItem("chess-teacher-verbosity") || "normal";
  for (const level of ["terse", "normal", "verbose"] as const) {
    const tab = document.createElement("button");
    tab.className = "verbosity-tab";
    tab.textContent = level.charAt(0).toUpperCase() + level.slice(1);
    tab.dataset.level = level;
    if (level === savedVerbosity) tab.classList.add("active");
    tab.addEventListener("click", () => {
      verbosityTabs.querySelectorAll(".verbosity-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      localStorage.setItem("chess-teacher-verbosity", level);
    });
    verbosityTabs.appendChild(tab);
  }

  // Theme selector
  const themeLabel = document.createElement("div");
  themeLabel.className = "menu-label";
  themeLabel.textContent = "theme";
  hamburgerMenu.appendChild(themeLabel);

  const themeSelect = document.createElement("select");
  themeSelect.className = "elo-select"; // reuse same styling as ELO select in menu
  const builtInThemes: [string, string][] = [
    ["dark", "Dark"],
    ["light", "Light"],
    ["wood", "Wood"],
    ["marble", "Marble"],
    ["rose", "Rose"],
    ["clean", "Clean"],
  ];
  for (const [value, label] of builtInThemes) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    themeSelect.appendChild(opt);
  }

  hamburgerMenu.appendChild(themeSelect);

  const themeDescInput = document.createElement("input");
  themeDescInput.type = "text";
  themeDescInput.placeholder = "Describe a theme\u2026";
  themeDescInput.className = "fen-input"; // reuse FEN input styling
  hamburgerMenu.appendChild(themeDescInput);

  const generateBtn = document.createElement("button");
  generateBtn.textContent = "Generate";
  hamburgerMenu.appendChild(generateBtn);

  generateBtn.addEventListener("click", async () => {
    const desc = themeDescInput.value.trim();
    if (!desc) return;

    generateBtn.textContent = "Generating\u2026";
    generateBtn.disabled = true;

    try {
      const resp = await fetch("/api/theme/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: desc }),
      });
      if (!resp.ok) {
        throw new Error("Generation failed");
      }
      const palette = await resp.json() as CustomTheme;
      palette.lastUsed = Date.now();

      // Save and apply
      const themes = saveCustomTheme(palette);
      applyCustomTheme(palette);

      // Update dropdown
      localStorage.setItem("chess-teacher-theme", `custom:${palette.label}`);
      rebuildThemeOptions(themes);
      themeSelect.value = `custom:${palette.label}`;

      themeDescInput.value = "";
    } catch {
      generateBtn.style.borderColor = "#f87171";
      setTimeout(() => { generateBtn.style.borderColor = ""; }, 1500);
    } finally {
      generateBtn.textContent = "Generate";
      generateBtn.disabled = false;
    }
  });

  // Also generate on Enter in the description input
  themeDescInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      generateBtn.click();
    }
  });

  // Theme change handler
  themeSelect.addEventListener("change", () => {
    const val = themeSelect.value;

    if (val.startsWith("custom:")) {
      const label = val.slice(7); // strip "custom:" prefix
      const themes = loadCustomThemes();
      const theme = themes.find(t => t.label === label);
      if (theme) {
        touchCustomTheme(label);
        applyCustomTheme(theme);
        localStorage.setItem("chess-teacher-theme", val);
      }
    } else {
      // Built-in theme
      clearCustomThemeVars();
      document.documentElement.setAttribute("data-theme", val);
      localStorage.setItem("chess-teacher-theme", val);
      updateBoardColors();
    }
  });

  function rebuildThemeOptions(customThemes: CustomTheme[]) {
    // Remove all options
    themeSelect.innerHTML = "";

    // Built-in themes
    for (const [value, label] of builtInThemes) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      themeSelect.appendChild(opt);
    }

    // Separator + custom themes
    if (customThemes.length > 0) {
      const sep = document.createElement("option");
      sep.disabled = true;
      sep.textContent = "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500";
      themeSelect.appendChild(sep);

      for (const ct of customThemes) {
        const opt = document.createElement("option");
        opt.value = `custom:${ct.label}`;
        opt.textContent = ct.label;
        themeSelect.appendChild(opt);
      }
    }
  }

  // Initialize dropdown with any saved custom themes
  rebuildThemeOptions(loadCustomThemes());

  // Set correct initial value (may be custom theme)
  themeSelect.value = savedTheme;

  const shortcutsRef = document.createElement("div");
  shortcutsRef.className = "shortcuts-ref";
  shortcutsRef.innerHTML =
    "<kbd>\u2190</kbd> <kbd>\u2192</kbd> navigate moves<br>" +
    "<kbd>\u2191</kbd> <kbd>\u2193</kbd> <kbd>Home</kbd> <kbd>End</kbd> first / last<br>" +
    "<kbd>n</kbd> new game";
  hamburgerMenu.appendChild(shortcutsRef);

  // Debug toggle
  const debugLabel = document.createElement("div");
  debugLabel.className = "menu-label";
  debugLabel.textContent = "developer";
  hamburgerMenu.appendChild(debugLabel);

  const debugToggle = document.createElement("label");
  debugToggle.className = "debug-toggle";
  const debugCheckbox = document.createElement("input");
  debugCheckbox.type = "checkbox";
  debugCheckbox.checked = localStorage.getItem("chess-teacher-debug") === "true";
  debugToggle.appendChild(debugCheckbox);
  debugToggle.appendChild(document.createTextNode(" Show LLM Prompts"));
  hamburgerMenu.appendChild(debugToggle);

  debugCheckbox.addEventListener("change", () => {
    localStorage.setItem("chess-teacher-debug", String(debugCheckbox.checked));
  });

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

  // Coach
  const coachSelectLabel = document.createElement("div");
  coachSelectLabel.className = "section-label";
  coachSelectLabel.textContent = "Coach";
  rightPanel.appendChild(coachSelectLabel);

  const coachSelect = document.createElement("select");
  coachSelect.className = "elo-select-main";
  const savedCoach = localStorage.getItem("chess-teacher-coach") || "Anna Cramling";
  const coachOptions: [string, string][] = [
    ["Anna Cramling", "Anna Cramling"],
    ["Daniel Naroditsky", "Daniel Naroditsky"],
    ["GothamChess", "GothamChess"],
    ["GM Ben Finegold", "GM Ben Finegold"],
    ["Hikaru", "Hikaru"],
    ["Judit Polgar", "Judit Polgar"],
    ["Magnus Carlsen", "Magnus Carlsen"],
    ["Vishy Anand", "Vishy Anand"],
    ["Garry Kasparov", "Garry Kasparov"],
    ["Mikhail Botvinnik", "Mikhail Botvinnik"],
    ["Paul Morphy", "Paul Morphy"],
    ["Mikhail Tal", "Mikhail Tal"],
    ["Jose Raul Capablanca", "Jose Raul Capablanca"],
    ["Faustino Oro", "Faustino Oro"],
  ];
  for (const [value, label] of coachOptions) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    if (value === savedCoach) opt.selected = true;
    coachSelect.appendChild(opt);
  }
  rightPanel.appendChild(coachSelect);

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

  // --- Markdown helper ---
  function makeCopyButton(text: string): HTMLButtonElement {
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.textContent = "copy";
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      navigator.clipboard.writeText(text).then(() => {
        btn.textContent = "copied";
        setTimeout(() => { btn.textContent = "copy"; }, 1500);
      }).catch(() => {
        btn.textContent = "failed";
        setTimeout(() => { btn.textContent = "copy"; }, 1500);
      });
    });
    return btn;
  }

  function parseSimpleMarkdown(text: string): string {
    // Escape HTML to prevent XSS
    const escaped = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");

    // Convert **bold** to <strong>
    return escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }

  // --- Coaching display ---
  function showCoaching(coaching: CoachingData) {
    const debugEnabled = localStorage.getItem("chess-teacher-debug") === "true";

    // Debug: log the grounded prompt to console
    if (coaching.debug_prompt && debugEnabled) {
      console.group(`%c[Coach Prompt] ply ${gc.getCurrentPly()}`, "color: #4ade80; font-weight: bold");
      console.log(coaching.debug_prompt);
      console.groupEnd();
    }

    // Collapsible debug bubble showing the prompt sent to LLM
    if (coaching.debug_prompt && debugEnabled) {
      const debugBubble = document.createElement("details");
      debugBubble.className = "coach-debug";
      const summary = document.createElement("summary");
      summary.textContent = "LLM prompt";
      debugBubble.appendChild(summary);
      debugBubble.appendChild(makeCopyButton(coaching.debug_prompt!));
      const pre = document.createElement("pre");
      pre.textContent = coaching.debug_prompt;
      debugBubble.appendChild(pre);
      coachMessages.appendChild(debugBubble);
    }

    const msg = document.createElement("div");
    msg.className = `coach-message ${coaching.quality}`;
    msg.innerHTML = parseSimpleMarkdown(coaching.message);
    msg.dataset.ply = String(gc.getCurrentPly());
    msg.addEventListener("click", () => {
      const ply = parseInt(msg.dataset.ply!, 10);
      gc.jumpToPly(ply);
    });
    msg.appendChild(makeCopyButton(coaching.message));
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

  // Initialize coach from localStorage before creating session
  gc.setCoachName(savedCoach);

  // Create initial server session
  gc.newGame();

  requestAnimationFrame(() => updateBoardColors());

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

  // Coach select
  coachSelect.addEventListener("change", () => {
    gc.setCoachName(coachSelect.value);
    localStorage.setItem("chess-teacher-coach", coachSelect.value);
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

  // Remote engine worker for server-dispatched analysis
  const remoteEngine = new BrowserEngine();
  remoteEngine.init("/static/vendor/stockfish/stockfish.js").then(() => {
    const remote = new RemoteUCI(remoteEngine);
    remote.connect();
    console.log("[RemoteUCI] Remote engine worker initialized");
  });
}

document.addEventListener("DOMContentLoaded", init);
