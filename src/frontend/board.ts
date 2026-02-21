import { Chessground } from "chessground";
import { Api } from "chessground/api";
import { Config } from "chessground/config";

export function createBoard(element: HTMLElement, config?: Partial<Config>): Api {
  const defaults: Partial<Config> = {
    fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    orientation: "white",
    movable: {
      free: false,
      color: "both",
    },
    draggable: {
      enabled: true,
      showGhost: true,
    },
    animation: {
      enabled: true,
      duration: 200,
    },
  };
  return Chessground(element, { ...defaults, ...config });
}
