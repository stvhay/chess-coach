import { Chess, Square } from "chess.js";
import { Api } from "chessground/api";
import { Key } from "chessground/types";
import { BrowserEngine, EvalCallback } from "./eval";

export type PromotionPiece = "q" | "r" | "b" | "n";

/** Callback when the move list changes. Receives full SAN move list. */
export type MoveListCallback = (moves: string[]) => void;

/** Callback to ask the user which piece to promote to. */
export type PromotionCallback = (
  orig: Key,
  dest: Key,
) => Promise<PromotionPiece>;

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

  /**
   * Handle a move made on the board. Called from chessground's after callback.
   * Returns true if the move was valid and applied.
   */
  async handleMove(orig: Key, dest: Key): Promise<boolean> {
    // Check if this is a promotion
    const isPromotion = this.isPromotionMove(orig, dest);
    let promotion: PromotionPiece = "q";

    if (isPromotion && this.onPromotion) {
      promotion = await this.onPromotion(orig, dest);
    }

    const move = this.game.move({
      from: orig as Square,
      to: dest as Square,
      promotion: isPromotion ? promotion : undefined,
    });

    if (!move) {
      // Invalid move — resync board to undo the visual move
      this.syncBoard();
      return false;
    }

    this.syncBoard();
    this.notifyMoveList();
    this.updateEval();
    return true;
  }

  /** Reset to starting position. */
  newGame(): void {
    this.game = new Chess();
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
    this.board.set({
      fen: this.game.fen(),
      turnColor,
      movable: {
        color: turnColor,
        dests: legalDests(this.game),
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
}
