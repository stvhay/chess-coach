import uuid
from dataclasses import dataclass, field

import chess

from server.engine import EngineAnalysis


@dataclass
class GameState:
    board: chess.Board = field(default_factory=chess.Board)
    depth: int = 10


def _game_status(board: chess.Board) -> str:
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.is_insufficient_material() or board.can_claim_draw():
        return "draw"
    return "playing"


def _game_result(board: chess.Board) -> str | None:
    if board.is_checkmate():
        return "0-1" if board.turn == chess.WHITE else "1-0"
    if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_draw():
        return "1/2-1/2"
    return None


class GameManager:
    def __init__(self, engine: EngineAnalysis):
        self._engine = engine
        self._sessions: dict[str, GameState] = {}

    def new_game(self, depth: int = 10) -> tuple[str, str, str]:
        """Create a new game session. Returns (session_id, fen, status)."""
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = GameState(depth=depth)
        return session_id, chess.STARTING_FEN, "playing"

    def get_game(self, session_id: str) -> GameState | None:
        return self._sessions.get(session_id)

    async def make_move(
        self, session_id: str, move_uci: str
    ) -> dict:
        """Apply player move, get Stockfish response, return result dict."""
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(f"Session not found: {session_id}")

        board = state.board

        try:
            move = chess.Move.from_uci(move_uci)
        except (chess.InvalidMoveError, ValueError) as e:
            raise ValueError(f"Invalid move format: {move_uci}") from e

        if move not in board.legal_moves:
            raise ValueError(f"Illegal move: {move_uci}")

        player_san = board.san(move)
        board.push(move)

        status = _game_status(board)
        if status != "playing":
            return {
                "fen": board.fen(),
                "player_move_san": player_san,
                "opponent_move_uci": None,
                "opponent_move_san": None,
                "status": status,
                "result": _game_result(board),
            }

        moves = await self._engine.best_moves(
            board.fen(), n=1, depth=state.depth
        )
        if not moves:
            raise RuntimeError("Engine returned no moves")

        opponent_uci = moves[0].uci
        opponent_move = chess.Move.from_uci(opponent_uci)
        opponent_san = board.san(opponent_move)
        board.push(opponent_move)

        status = _game_status(board)
        return {
            "fen": board.fen(),
            "player_move_san": player_san,
            "opponent_move_uci": opponent_uci,
            "opponent_move_san": opponent_san,
            "status": status,
            "result": _game_result(board),
        }
