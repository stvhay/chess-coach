import { Chess, Square } from "chess.js";
import { Api } from "chessground/api";
import { DrawShape } from "chessground/draw";
import { Key } from "chessground/types";
import { BrowserEngine, EvalCallback, MultiPVCallback } from "./eval";
import { createGame, sendMove, MoveResponse, CoachingData } from "./api";

export type PromotionPiece = "q" | "r" | "b" | "n";

/** Callback when the move list changes. Receives full SAN move list. */
export type MoveListCallback = (moves: string[]) => void;

/** Callback to ask the user which piece to promote to. */
export type PromotionCallback = (
  orig: Key,
  dest: Key,
) => Promise<PromotionPiece>;

/** Callback when game status changes. */
export type StatusCallback = (status: string, result: string | null) => void;

/** Callback when coaching data arrives. */
export type CoachingCallback = (coaching: CoachingData) => void;

/** Callback when the viewed ply changes (for UI navigation state). */
export type PlyChangeCallback = (ply: number, maxPly: number) => void;

/**
 * Compute chessground-compatible legal destinations from a chess.js instance.
 * Returns a Map from source square to array of destination squares.
 */
function legalDests(game: Chess): Map<Key, Key[]> {
  const dests = new Map<Key, Key[]>();
  for (const move of game.moves({ verbose: true })) {
    const src = move.from as Key;
    const existing = dests.get(src);
    if (existing) {
      existing.push(move.to as Key);
    } else {
      dests.set(src, [move.to as Key]);
    }
  }
  return dests;
}

/**
 * Convert chess.js color ("w" | "b") to chessground color ("white" | "black").
 */
function toColor(c: "w" | "b"): "white" | "black" {
  return c === "w" ? "white" : "black";
}

/**
 * GameController owns the chess game state and coordinates the board UI,
 * move validation, and engine evaluation.
 */
export class GameController {
  private game: Chess;
  private board: Api;
  private engine: BrowserEngine | null;
  private onMoveList: MoveListCallback | null = null;
  private onPromotion: PromotionCallback | null = null;
  private onEval: EvalCallback | null = null;
  private sessionId: string | null = null;
  private playerColor: "w" | "b" = "w";
  private onStatus: StatusCallback | null = null;
  private onCoaching: CoachingCallback | null = null;
  private onPlyChange: PlyChangeCallback | null = null;
  private onMultiPV: MultiPVCallback | null = null;
  private thinking = false;
  private currentPly = 0;
  private maxPly = 0;
  private coachingByPly: Map<number, CoachingData> = new Map();
  private eloProfile: string = "intermediate";
  private coachName: string = "a chess coach";

  constructor(board: Api, engine: BrowserEngine | null) {
    this.game = new Chess();
    this.board = board;
    this.engine = engine;
    this.syncBoard();
  }

  /** Register callback for move list updates. */
  setMoveListCallback(cb: MoveListCallback): void {
    this.onMoveList = cb;
  }

  /** Register callback for promotion piece selection. */
  setPromotionCallback(cb: PromotionCallback): void {
    this.onPromotion = cb;
  }

  /** Register callback for eval updates. */
  setEvalCallback(cb: EvalCallback): void {
    this.onEval = cb;
  }

  /** Register callback for game status changes. */
  setStatusCallback(cb: StatusCallback): void {
    this.onStatus = cb;
  }

  /** Register callback for coaching updates. */
  setCoachingCallback(cb: CoachingCallback): void {
    this.onCoaching = cb;
  }

  /** Register callback for ply change events. */
  setPlyChangeCallback(cb: PlyChangeCallback): void {
    this.onPlyChange = cb;
  }

  /** Register callback for MultiPV eval updates. */
  setMultiPVCallback(cb: MultiPVCallback): void {
    this.onMultiPV = cb;
  }

  /** Set ELO profile for coaching depth/style. */
  setEloProfile(profile: string): void {
    this.eloProfile = profile;
  }

  /** Set coach name for persona. */
  setCoachName(name: string): void {
    this.coachName = name;
  }

  /**
   * Handle a move made on the board. Called from chessground's after callback.
   * Sends move to server, receives opponent response, applies it.
   */
  async handleMove(orig: Key, dest: Key): Promise<boolean> {
    if (this.thinking) return false;
    this.clearCoaching();

    // Check if this is a promotion
    const isPromotion = this.isPromotionMove(orig, dest);
    let promotion: PromotionPiece = "q";

    if (isPromotion && this.onPromotion) {
      promotion = await this.onPromotion(orig, dest);
    }

    // Build UCI move string
    let moveUci = `${orig}${dest}`;
    if (isPromotion) {
      moveUci += promotion;
    }

    // Apply player move locally first
    const localMove = this.game.move({
      from: orig as Square,
      to: dest as Square,
      promotion: isPromotion ? promotion : undefined,
    });

    if (!localMove) {
      this.syncBoard();
      return false;
    }

    this.maxPly = this.game.history().length;
    this.currentPly = this.maxPly;
    this.syncBoard();
    this.notifyMoveList();
    this.notifyPlyChange();

    // If no server session, just play locally (both sides)
    if (!this.sessionId) {
      this.updateEval();
      return true;
    }

    // Check if game over after player move
    if (this.game.isGameOver()) {
      this.notifyStatus();
      this.updateEval();
      return true;
    }

    // Send to server and get opponent response
    this.setThinking(true);
    try {
      const verbosity = localStorage.getItem("chess-teacher-verbosity") || "normal";
      const resp = await sendMove(this.sessionId, moveUci, verbosity);
      this.handleCoaching(resp.coaching);
      this.applyOpponentMove(resp);
    } catch (err) {
      console.error("Server move failed:", err);
      // Game continues locally — graceful degradation
    } finally {
      this.setThinking(false);
    }

    this.updateEval();
    return true;
  }

  /** Reset to starting position and create a server session. */
  async newGame(): Promise<void> {
    this.game = new Chess();
    this.playerColor = "w";
    this.thinking = false;
    this.currentPly = 0;
    this.maxPly = 0;
    this.coachingByPly.clear();
    this.board.setAutoShapes([]);

    try {
      const resp = await createGame(10, this.eloProfile, this.coachName);
      this.sessionId = resp.session_id;
    } catch (err) {
      console.warn("Failed to create server session:", err);
      this.sessionId = null;
    }

    this.syncBoard();
    this.notifyMoveList();
    this.updateEval();
  }

  /** Set position from FEN string. Returns true if FEN was valid. */
  setPosition(fen: string): boolean {
    try {
      this.game = new Chess(fen);
    } catch {
      return false;
    }
    this.syncBoard();
    this.notifyMoveList();
    this.updateEval();
    return true;
  }

  /** Get current FEN. */
  fen(): string {
    return this.game.fen();
  }

  /** Get move history as SAN strings. */
  history(): string[] {
    return this.game.history();
  }

  /** Check if game is over. */
  isGameOver(): boolean {
    return this.game.isGameOver();
  }

  /** Jump to a specific ply in the game history. */
  jumpToPly(ply: number): void {
    if (ply < 0 || ply > this.maxPly) return;
    this.currentPly = ply;

    // Rebuild position from move history
    const fullHistory = this.game.history({ verbose: true });
    const temp = new Chess();
    for (let i = 0; i < ply; i++) {
      temp.move(fullHistory[i].san);
    }

    // Sync board to this position without touching game state
    const turnColor = toColor(temp.turn());
    const atLatest = this.isAtLatest();
    this.board.set({
      fen: temp.fen(),
      turnColor,
      movable: {
        color: atLatest && !this.thinking ? toColor(this.playerColor) : undefined,
        dests: atLatest && !this.thinking ? legalDests(temp) : new Map(),
      },
      lastMove: ply > 0
        ? [fullHistory[ply - 1].from as Key, fullHistory[ply - 1].to as Key]
        : undefined,
      check: temp.isCheck() ? turnColor : undefined,
    });

    // Show coaching for this ply if it exists
    const coaching = this.coachingByPly.get(ply);
    if (coaching) {
      this.showCoachingShapes(coaching);
    } else {
      this.board.setAutoShapes([]);
    }

    // Eval the viewed position
    if (this.engine) {
      if (this.onMultiPV) {
        this.engine.evaluateMultiPV(temp.fen(), this.onMultiPV);
      } else if (this.onEval) {
        this.engine.evaluate(temp.fen(), this.onEval);
      }
    }

    this.notifyPlyChange();
  }

  /** Step one move forward in history. */
  stepForward(): void {
    this.jumpToPly(this.currentPly + 1);
  }

  /** Step one move back in history. */
  stepBack(): void {
    this.jumpToPly(this.currentPly - 1);
  }

  /** Whether we're viewing the latest position (live play). */
  isAtLatest(): boolean {
    return this.currentPly === this.maxPly;
  }

  /** Get the current viewed ply. */
  getCurrentPly(): number {
    return this.currentPly;
  }

  /** Get the max ply. */
  getMaxPly(): number {
    return this.maxPly;
  }

  /** Get the FEN of the currently viewed position (may differ from live game). */
  viewedFen(): string {
    if (this.isAtLatest()) return this.game.fen();
    const fullHistory = this.game.history({ verbose: true });
    const temp = new Chess();
    for (let i = 0; i < this.currentPly; i++) {
      temp.move(fullHistory[i].san);
    }
    return temp.fen();
  }

  /** Get coaching data for a specific ply. */
  getCoachingAtPly(ply: number): CoachingData | undefined {
    return this.coachingByPly.get(ply);
  }

  /** Convert UCI move strings to SAN notation using the currently viewed position. */
  uciToSan(uciMoves: string[]): string[] {
    const temp = new Chess(this.viewedFen());
    const san: string[] = [];
    for (const uci of uciMoves) {
      try {
        const move = temp.move({
          from: uci.slice(0, 2) as Square,
          to: uci.slice(2, 4) as Square,
          promotion: uci.length > 4 ? uci[4] as PromotionPiece : undefined,
        });
        if (move) san.push(move.san);
        else break;
      } catch {
        break;
      }
    }
    return san;
  }

  /** Sync chessground board state with chess.js game state. */
  private syncBoard(): void {
    const turnColor = toColor(this.game.turn());
    const isPlayerTurn = this.game.turn() === this.playerColor;
    this.board.set({
      fen: this.game.fen(),
      turnColor,
      movable: {
        color: isPlayerTurn && !this.thinking ? toColor(this.playerColor) : undefined,
        dests: isPlayerTurn && !this.thinking ? legalDests(this.game) : new Map(),
      },
      lastMove: this.getLastMove(),
      check: this.game.isCheck() ? turnColor : undefined,
    });
  }

  /** Get the last move as [orig, dest] for chessground highlight. */
  private getLastMove(): Key[] | undefined {
    const history = this.game.history({ verbose: true });
    if (history.length === 0) return undefined;
    const last = history[history.length - 1];
    return [last.from as Key, last.to as Key];
  }

  /** Check if a move from orig to dest would be a pawn promotion. */
  private isPromotionMove(orig: Key, dest: Key): boolean {
    const piece = this.game.get(orig as Square);
    if (!piece || piece.type !== "p") return false;
    const destRank = dest[1];
    return (piece.color === "w" && destRank === "8") ||
           (piece.color === "b" && destRank === "1");
  }

  /** Notify the move list callback with current history. */
  private notifyMoveList(): void {
    this.onMoveList?.(this.game.history());
  }

  /** Notify ply change callback. */
  private notifyPlyChange(): void {
    this.onPlyChange?.(this.currentPly, this.maxPly);
  }

  /** Trigger engine evaluation of current position. */
  private updateEval(): void {
    if (this.engine) {
      if (this.onMultiPV) {
        this.engine.evaluateMultiPV(this.game.fen(), this.onMultiPV);
      } else if (this.onEval) {
        this.engine.evaluate(this.game.fen(), this.onEval);
      }
    }
  }

  /** Apply the opponent's move from the server response. */
  private applyOpponentMove(resp: MoveResponse): void {
    if (!resp.opponent_move_uci) {
      // Game ended on player's move
      this.notifyStatus();
      return;
    }

    const from = resp.opponent_move_uci.slice(0, 2) as Key;
    const to = resp.opponent_move_uci.slice(2, 4) as Key;
    const promotion = resp.opponent_move_uci.length > 4
      ? resp.opponent_move_uci[4] as PromotionPiece
      : undefined;

    // Apply to chess.js
    this.game.move({
      from: from as Square,
      to: to as Square,
      promotion,
    });

    // Sync full state — chessground animates the diff via lastMove
    this.maxPly = this.game.history().length;
    this.currentPly = this.maxPly;
    this.syncBoard();
    this.notifyMoveList();
    this.notifyPlyChange();

    if (resp.status !== "playing") {
      this.onStatus?.(resp.status, resp.result);
    }
  }

  /** Lock/unlock the board during opponent thinking. */
  private setThinking(thinking: boolean): void {
    this.thinking = thinking;
    if (thinking) {
      this.board.set({
        movable: { color: undefined },
      });
    } else {
      this.syncBoard();
    }
  }

  /** Display coaching annotations on the board and fire coaching callback. */
  private handleCoaching(coaching: CoachingData | null): void {
    if (!coaching) {
      this.board.setAutoShapes([]);
      return;
    }

    // Store coaching by ply for later navigation
    this.coachingByPly.set(this.currentPly, coaching);

    this.showCoachingShapes(coaching);
    this.onCoaching?.(coaching);
  }

  /** Draw coaching arrows and highlights on the board. */
  private showCoachingShapes(coaching: CoachingData): void {
    const shapes: DrawShape[] = [];

    for (const arrow of coaching.arrows) {
      shapes.push({
        orig: arrow.orig as Key,
        dest: arrow.dest as Key,
        brush: arrow.brush,
      });
    }

    for (const highlight of coaching.highlights) {
      shapes.push({
        orig: highlight.square as Key,
        brush: highlight.brush,
      });
    }

    this.board.setAutoShapes(shapes);
  }

  /** Clear coaching annotations (called before player's next move). */
  private clearCoaching(): void {
    this.board.setAutoShapes([]);
  }

  /** Notify status callback based on current game state. */
  private notifyStatus(): void {
    if (this.game.isCheckmate()) {
      const winner = this.game.turn() === "w" ? "Black" : "White";
      this.onStatus?.("checkmate", winner === "White" ? "1-0" : "0-1");
    } else if (this.game.isStalemate()) {
      this.onStatus?.("stalemate", "1/2-1/2");
    } else if (this.game.isDraw()) {
      this.onStatus?.("draw", "1/2-1/2");
    }
  }
}
