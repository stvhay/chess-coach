/**
 * RemoteUCI — bridges server WebSocket requests to a dedicated BrowserEngine worker.
 *
 * The server sends JSON requests (evaluate, analyze_lines, best_moves, find_mate_threats)
 * and this module dispatches them to a local WASM Stockfish worker, then sends
 * structured JSON results back over the WebSocket.
 */

import { Chess } from "chess.js";
import { BrowserEngine, EvalInfo, EvalLine } from "./eval";

interface EngineRequest {
  id: string;
  method: string;
  params: Record<string, unknown>;
}

export class RemoteUCI {
  private ws: WebSocket | null = null;
  private engine: BrowserEngine;
  private reconnectTimer: number | null = null;

  constructor(engine: BrowserEngine) {
    this.engine = engine;
  }

  /** Connect to the server's /ws/engine endpoint. */
  connect(): void {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${location.host}/ws/engine`;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log("[RemoteUCI] Connected");
      if (this.reconnectTimer !== null) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    };

    this.ws.onmessage = (event) => {
      this.handleMessage(event.data);
    };

    this.ws.onclose = () => {
      console.log("[RemoteUCI] Disconnected, reconnecting in 3s...");
      this.reconnectTimer = window.setTimeout(() => this.connect(), 3000);
    };

    this.ws.onerror = (err) => {
      console.error("[RemoteUCI] WebSocket error", err);
    };
  }

  /** Send a JSON response back to the server. */
  private send(data: object): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  /** Handle an incoming server request. */
  private async handleMessage(raw: string): Promise<void> {
    let req: EngineRequest;
    try {
      req = JSON.parse(raw);
    } catch {
      return;
    }

    try {
      let result: unknown;
      switch (req.method) {
        case "evaluate":
          result = await this.handleEvaluate(req.params);
          break;
        case "analyze_lines":
          result = await this.handleAnalyzeLines(req.params);
          break;
        case "best_moves":
          result = await this.handleBestMoves(req.params);
          break;
        case "find_mate_threats":
          result = await this.handleFindMateThreats(req.params);
          break;
        default:
          this.send({ id: req.id, error: `Unknown method: ${req.method}` });
          return;
      }
      this.send({ id: req.id, result });
    } catch (err) {
      this.send({ id: req.id, error: String(err) });
    }
  }

  private async handleEvaluate(params: Record<string, unknown>): Promise<object> {
    const fen = params.fen as string;
    const depth = (params.depth as number) ?? 20;
    const info = await this.engine.evaluateAsync(fen, depth);
    return {
      score_cp: info.scoreCp,
      score_mate: info.scoreMate,
      depth: info.depth,
      best_move: info.pv[0] ?? null,
      pv: info.pv,
    };
  }

  private async handleAnalyzeLines(params: Record<string, unknown>): Promise<object[]> {
    const fen = params.fen as string;
    const n = (params.n as number) ?? 5;
    const depth = (params.depth as number) ?? 16;

    const lines = await this.engine.evaluateMultiPVAsync(fen, n, depth);
    const chess = new Chess(fen);

    return lines.map((line: EvalLine) => {
      const uci = line.pv[0] ?? "";
      let san = uci;
      try {
        // Convert UCI to SAN using chess.js
        const move = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
        if (move) {
          san = move.san;
          chess.undo();
        }
      } catch { /* leave as UCI */ }
      return {
        uci,
        san,
        score_cp: line.scoreCp,
        score_mate: line.scoreMate,
        pv: line.pv,
        depth,
      };
    });
  }

  private async handleBestMoves(params: Record<string, unknown>): Promise<object[]> {
    const fen = params.fen as string;
    const n = (params.n as number) ?? 3;
    const depth = (params.depth as number) ?? 20;

    const lines = await this.engine.evaluateMultiPVAsync(fen, n, depth);

    return lines.map((line: EvalLine) => ({
      uci: line.pv[0] ?? "",
      score_cp: line.scoreCp,
      score_mate: line.scoreMate,
    }));
  }

  private async handleFindMateThreats(params: Record<string, unknown>): Promise<object[]> {
    const fen = params.fen as string;
    const maxDepth = (params.max_depth as number) ?? 3;
    const evalDepth = (params.eval_depth as number) ?? 10;

    const chess = new Chess(fen);
    const colorName = chess.turn() === "w" ? "white" : "black";
    const threats: object[] = [];

    for (const move of chess.moves({ verbose: true })) {
      chess.move(move.san);
      const afterFen = chess.fen();
      chess.undo();

      const info = await this.engine.evaluateAsync(afterFen, evalDepth);

      if (info.scoreMate !== null) {
        const mate = info.scoreMate;
        const depth = Math.abs(mate);
        const isOurMate = mate < 0;

        if (isOurMate && depth <= maxDepth) {
          threats.push({
            threatening_color: colorName,
            mating_square: move.to,
            depth,
            mating_move: move.san,
          });
          break;
        }
      }
    }

    return threats;
  }

  /** Disconnect and stop reconnecting. */
  destroy(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onclose = null; // Prevent reconnect
      this.ws.close();
      this.ws = null;
    }
  }
}
