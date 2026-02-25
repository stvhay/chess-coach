from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

import chess

from server.analysis import analyze
from server.coach import Arrow, assess_move
from server.elo_profiles import get_profile
from server.engine import EngineAnalysis
from server.game_tree import build_coaching_tree
from server.knowledge import query_knowledge
from server.llm import ChessTeacher
from server.opponent import select_opponent_move
from server.rag import ChessRAG
from server.report import serialize_report


@dataclass
class GameState:
    board: chess.Board = field(default_factory=chess.Board)
    depth: int = 10
    elo_profile: str = "intermediate"
    coach_name: str = "Anna Cramling"


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
    def __init__(
        self,
        engine: EngineAnalysis,
        teacher: ChessTeacher | None = None,
        rag: ChessRAG | None = None,
        rag_top_k: int = 3,
    ):
        self._engine = engine
        self._teacher = teacher
        self._rag = rag
        self._rag_top_k = rag_top_k
        self._sessions: dict[str, GameState] = {}

    def new_game(
        self, depth: int = 10, elo_profile: str = "intermediate", coach_name: str = "Anna Cramling"
    ) -> tuple[str, str, str]:
        """Create a new game session. Returns (session_id, fen, status)."""
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = GameState(
            depth=depth, elo_profile=elo_profile, coach_name=coach_name
        )
        return session_id, chess.STARTING_FEN, "playing"

    def get_game(self, session_id: str) -> GameState | None:
        return self._sessions.get(session_id)

    async def _enrich_coaching(
        self,
        coaching_data,
        board: chess.Board,
        board_before: chess.Board,
        player_move_uci: str,
        eval_before,
        elo_profile: str,
        coach_name: str,
        verbosity: str = "normal",
    ) -> None:
        """Game-tree coaching pipeline with RAG + LLM."""
        profile = get_profile(elo_profile)

        tree = await build_coaching_tree(
            self._engine, board_before, player_move_uci, eval_before, profile
        )

        # RAG enrichment
        rag_context = ""
        if self._rag is not None:
            report = analyze(board.copy())
            rag_context = await query_knowledge(
                self._rag, report,
                coaching_data.quality.value,
                coaching_data.tactics_summary,
                n=self._rag_top_k,
            )

        # Serialize report
        prompt = serialize_report(
            tree,
            quality=coaching_data.quality.value,
            cp_loss=coaching_data.severity,
            rag_context=rag_context,
        )

        # Build full debug prompt (system + user) if teacher is available
        if self._teacher is not None:
            coaching_data.debug_prompt = self._teacher.build_debug_prompt(
                prompt, coach=coach_name, verbosity=verbosity,
                move_quality=coaching_data.quality.value, elo_profile=elo_profile,
            )
        else:
            coaching_data.debug_prompt = prompt

        # Update arrows from tree alternatives
        alts = tree.alternatives()
        if alts:
            top_uci = alts[0].move.uci()
            coaching_data.arrows = [a for a in coaching_data.arrows if a.brush != "green"]
            if len(top_uci) >= 4:
                coaching_data.arrows.append(
                    Arrow(orig=top_uci[:2], dest=top_uci[2:4], brush="green")
                )

        # LLM
        if self._teacher is not None:
            llm_message = await self._teacher.explain_move(
                prompt, coach=coach_name, verbosity=verbosity,
                move_quality=coaching_data.quality.value, elo_profile=elo_profile,
            )
            if llm_message is not None:
                coaching_data.message = llm_message

    async def make_move(
        self, session_id: str, move_uci: str, verbosity: str = "normal",
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
        profile = get_profile(state.elo_profile)
        eval_before = await self._engine.evaluate(
            board.fen(), depth=profile.validate_depth
        )
        best_move_uci = eval_before.best_move

        board_before = board.copy()
        player_san = board.san(move)
        board.push(move)

        # Evaluate position after the player's move for coaching.
        eval_after = await self._engine.evaluate(
            board.fen(), depth=profile.validate_depth
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

        # Enrich coaching with two-pass pipeline + RAG + LLM (timeout so game never freezes).
        if coaching_data is not None:
            try:
                await asyncio.wait_for(
                    self._enrich_coaching(
                        coaching_data, board, board_before,
                        move_uci, eval_before, state.elo_profile,
                        state.coach_name,
                        verbosity=verbosity,
                    ),
                    timeout=20.0,
                )
            except asyncio.TimeoutError:
                logging.getLogger(__name__).warning("Coaching enrichment timed out")

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
                "debug_prompt": coaching_data.debug_prompt,
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

        result = await select_opponent_move(board, self._engine, teacher=self._teacher)
        opponent_move = chess.Move.from_uci(result.uci)
        board.push(opponent_move)

        status = _game_status(board)
        return {
            "fen": board.fen(),
            "player_move_san": player_san,
            "opponent_move_uci": result.uci,
            "opponent_move_san": result.san,
            "status": status,
            "result": _game_result(board),
            "coaching": coaching_dict,
        }
