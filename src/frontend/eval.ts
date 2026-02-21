/**
 * Browser Stockfish WASM wrapper.
 *
 * Loads stockfish-18-lite-single (from static/vendor/stockfish/) as a Web
 * Worker and communicates via the UCI protocol through postMessage.
 *
 * The vendored files come from the npm "stockfish" package v18.0.5
 * (https://github.com/nmrugg/stockfish.js, GPLv3).
 *
 * Usage:
 *   const engine = new BrowserEngine();
 *   await engine.init("/vendor/stockfish/stockfish.js");
 *   engine.evaluate(fen, (info) => console.log(info));
 *   engine.stop();
 *   engine.destroy();
 */

/** Structured evaluation info parsed from UCI "info" lines. */
export interface EvalInfo {
  depth: number;
  scoreCp: number | null;
  scoreMate: number | null;
  pv: string[];
  nodes?: number;
  nps?: number;
  time?: number;
  multipv?: number;
}

/** Callback invoked each time the engine emits a new info line. */
export type EvalCallback = (info: EvalInfo) => void;

/**
 * Wraps a Stockfish WASM Web Worker behind a simple evaluate/stop API.
 *
 * The worker speaks UCI: we send commands as strings via postMessage and
 * receive engine output lines back the same way.
 */
export class BrowserEngine {
  private worker: Worker | null = null;
  private onEval: EvalCallback | null = null;
  private ready = false;

  /**
   * Load the engine and wait for UCI initialization.
   *
   * @param wasmPath - URL to the stockfish JS file that will be loaded as a
   *   Worker (e.g. "/vendor/stockfish/stockfish.js"). The corresponding
   *   .wasm file must sit in the same directory.
   */
  async init(wasmPath: string): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      this.worker = new Worker(wasmPath);

      this.worker.onmessage = (e: MessageEvent) => {
        const line =
          typeof e.data === "string"
            ? e.data
            : (e.data?.toString?.() ?? "");

        if (line.includes("uciok")) {
          this.ready = true;
          resolve();
        }

        this.parseLine(line);
      };

      this.worker.onerror = (err) => {
        reject(
          new Error(
            `Stockfish worker failed to load: ${err.message ?? "unknown error"}`,
          ),
        );
      };

      // Start UCI handshake.
      this.worker.postMessage("uci");
    });
  }

  /** Whether the engine has completed UCI initialization. */
  isReady(): boolean {
    return this.ready;
  }

  /**
   * Parse a single UCI output line and fire the eval callback when
   * appropriate.  Only "info" lines that contain a score are forwarded.
   */
  private parseLine(line: string): void {
    if (!line.startsWith("info") || !line.includes("score")) return;

    const depthMatch = line.match(/\bdepth (\d+)/);
    const cpMatch = line.match(/\bscore cp (-?\d+)/);
    const mateMatch = line.match(/\bscore mate (-?\d+)/);
    const pvMatch = line.match(/ pv (.+)/);
    const nodesMatch = line.match(/\bnodes (\d+)/);
    const npsMatch = line.match(/\bnps (\d+)/);
    const timeMatch = line.match(/\btime (\d+)/);
    const multipvMatch = line.match(/\bmultipv (\d+)/);

    if (!depthMatch) return;

    const info: EvalInfo = {
      depth: parseInt(depthMatch[1], 10),
      scoreCp: cpMatch ? parseInt(cpMatch[1], 10) : null,
      scoreMate: mateMatch ? parseInt(mateMatch[1], 10) : null,
      pv: pvMatch ? pvMatch[1].split(" ") : [],
    };

    if (nodesMatch) info.nodes = parseInt(nodesMatch[1], 10);
    if (npsMatch) info.nps = parseInt(npsMatch[1], 10);
    if (timeMatch) info.time = parseInt(timeMatch[1], 10);
    if (multipvMatch) info.multipv = parseInt(multipvMatch[1], 10);

    this.onEval?.(info);
  }

  /**
   * Start evaluating a position.  The callback fires for each depth as
   * the engine searches deeper.
   *
   * Automatically stops any in-progress search before starting a new one.
   *
   * @param fen      - FEN string of the position to evaluate.
   * @param callback - Called with structured eval info at each depth.
   * @param depth    - Maximum search depth (default 20).
   */
  evaluate(fen: string, callback: EvalCallback, depth: number = 20): void {
    if (!this.worker || !this.ready) return;

    this.onEval = callback;
    this.worker.postMessage("stop");
    this.worker.postMessage("ucinewgame");
    this.worker.postMessage("isready");
    this.worker.postMessage(`position fen ${fen}`);
    this.worker.postMessage(`go depth ${depth}`);
  }

  /** Stop the current search. */
  stop(): void {
    this.worker?.postMessage("stop");
    this.onEval = null;
  }

  /** Terminate the worker entirely.  The engine cannot be reused after this. */
  destroy(): void {
    this.stop();
    this.worker?.terminate();
    this.worker = null;
    this.ready = false;
  }
}
