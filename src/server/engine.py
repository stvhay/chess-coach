from dataclasses import dataclass
import chess
import chess.engine


@dataclass
class Evaluation:
    score_cp: int | None
    score_mate: int | None
    depth: int
    best_move: str | None
    pv: list[str]


@dataclass
class MoveInfo:
    uci: str
    score_cp: int | None
    score_mate: int | None


class EngineAnalysis:
    def __init__(self, stockfish_path: str = "stockfish", hash_mb: int = 64):
        self._path = stockfish_path
        self._hash_mb = hash_mb
        self._engine: chess.engine.UciProtocol | None = None

    async def start(self):
        _, self._engine = await chess.engine.popen_uci(self._path)
        await self._engine.configure({"Hash": self._hash_mb})

    async def stop(self):
        if self._engine:
            await self._engine.quit()
            self._engine = None

    async def evaluate(self, fen: str, depth: int = 20) -> Evaluation:
        if self._engine is None:
            raise RuntimeError("Engine not started. Call start() first.")
        try:
            board = chess.Board(fen)
        except ValueError as e:
            raise ValueError(f"Invalid FEN: {fen}") from e
        result = await self._engine.analyse(board, chess.engine.Limit(depth=depth))
        score = result["score"].white()
        pv = result.get("pv", [])
        return Evaluation(
            score_cp=score.score(),
            score_mate=score.mate(),
            depth=result.get("depth", depth),
            best_move=pv[0].uci() if pv else None,
            pv=[m.uci() for m in pv],
        )

    async def best_moves(self, fen: str, n: int = 3, depth: int = 20) -> list[MoveInfo]:
        if self._engine is None:
            raise RuntimeError("Engine not started. Call start() first.")
        try:
            board = chess.Board(fen)
        except ValueError as e:
            raise ValueError(f"Invalid FEN: {fen}") from e
        results = await self._engine.analyse(
            board, chess.engine.Limit(depth=depth), multipv=n
        )
        if not isinstance(results, list):
            results = [results]
        moves = []
        for info in results:
            score = info["score"].white()
            pv = info.get("pv", [])
            if pv:
                moves.append(MoveInfo(
                    uci=pv[0].uci(),
                    score_cp=score.score(),
                    score_mate=score.mate(),
                ))
        return moves
