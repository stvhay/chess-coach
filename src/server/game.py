import uuid
from dataclasses import dataclass, field

import chess

from server.coach import assess_move
from server.engine import EngineAnalysis


@dataclass
class GameState:
    board: chess.Board = field(default_factory=chess.Board)
    depth: int = 10
    coaching_depth: int = 12


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

        # Evaluate position before the player's move for coaching.
        eval_before = await self._engine.evaluate(
            board.fen(), depth=state.coaching_depth
        )
        best_move_uci = eval_before.best_move

        board_before = board.copy()
        player_san = board.san(move)
        board.push(move)

        # Evaluate position after the player's move for coaching.
        eval_after = await self._engine.evaluate(
            board.fen(), depth=state.coaching_depth
        )

        # Assess the player's move for coaching feedback.
        coaching_data = None
        if best_move_uci is not None:
            coaching_data = assess_move(
                board_before=board_before,
                board_after=board.copy(),
                player_move_uci=move_uci,
                eval_before=eval_before,
                eval_after=eval_after,
                best_move_uci=best_move_uci,
            )

        coaching_dict = None
        if coaching_data is not None:
            coaching_dict = {
                "quality": coaching_data.quality.value,
                "message": coaching_data.message,
                "arrows": [
                    {"orig": a.orig, "dest": a.dest, "brush": a.brush}
                    for a in coaching_data.arrows
                ],
                "highlights": [
                    {"square": h.square, "brush": h.brush}
                    for h in coaching_data.highlights
                ],
                "severity": coaching_data.severity,
            }

        status = _game_status(board)
        if status != "playing":
            return {
                "fen": board.fen(),
                "player_move_san": player_san,
                "opponent_move_uci": None,
                "opponent_move_san": None,
                "status": status,
                "result": _game_result(board),
                "coaching": coaching_dict,
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
            "coaching": coaching_dict,
        }
