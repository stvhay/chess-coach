import { Chess, Square } from "chess.js";
import { Api } from "chessground/api";
import { Key } from "chessground/types";
import { BrowserEngine, EvalCallback } from "./eval";
import { createGame, sendMove, MoveResponse } from "./api";

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
  private thinking = false;

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

  /**
   * Handle a move made on the board. Called from chessground's after callback.
   * Sends move to server, receives opponent response, applies it.
   */
  async handleMove(orig: Key, dest: Key): Promise<boolean> {
    if (this.thinking) return false;

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

    this.syncBoard();
    this.notifyMoveList();

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
      const resp = await sendMove(this.sessionId, moveUci);
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

    try {
      const resp = await createGame();
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

  /** Trigger engine evaluation of current position. */
  private updateEval(): void {
    if (this.engine && this.onEval) {
      this.engine.evaluate(this.game.fen(), this.onEval);
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

    // Animate on board then sync
    this.board.move(from, to);
    this.syncBoard();
    this.notifyMoveList();

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
