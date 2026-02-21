import { Chessground } from "chessground";
import { Api } from "chessground/api";
import { Config } from "chessground/config";
import { Key } from "chessground/types";

export type AfterMoveCallback = (orig: Key, dest: Key) => void;

export function createBoard(
  element: HTMLElement,
  onMove?: AfterMoveCallback,
  config?: Partial<Config>,
): Api {
  const defaults: Partial<Config> = {
    fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    orientation: "white",
    movable: {
      free: false,
      color: "white",
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

  if (onMove) {
    defaults.movable = {
      ...defaults.movable,
      events: {
        after: onMove,
      },
    };
  }

  return Chessground(element, { ...defaults, ...config });
}
