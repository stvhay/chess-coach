"""Coaching assessment module.

Classifies player moves by centipawn loss and generates coaching feedback
with board annotations. Uses position analysis for tactical context.
Returns None for routine moves so the coach stays silent unless there is
something worth saying.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

import chess

from server.analysis import TacticalMotifs, analyze_tactics
from server.engine import Evaluation


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class MoveQuality(enum.Enum):
    BRILLIANT = "brilliant"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"


@dataclass
class Arrow:
    """A chessground arrow annotation."""
    orig: str
    dest: str
    brush: str  # "green", "red", "blue", "yellow"


@dataclass
class Highlight:
    """A chessground square highlight."""
    square: str
    brush: str


@dataclass
class CoachingResponse:
    """What the coach shows the player after a non-routine move."""
    quality: MoveQuality
    message: str
    arrows: list[Arrow] = field(default_factory=list)
    highlights: list[Highlight] = field(default_factory=list)
    severity: int = 0  # 0-100, higher = more urgent
    tactics_summary: str = ""
    debug_prompt: str = ""  # the grounded prompt sent to the LLM


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Large centipawn value used as a stand-in for forced mate.
_MATE_CP = 10_000


def _cp_value(ev: Evaluation) -> int:
    """Convert an Evaluation to a single centipawn integer.

    Mate scores are mapped to large positive/negative values so they
    compare correctly against centipawn-based thresholds.
    """
    if ev.score_mate is not None:
        # Positive mate = player is mating, negative = getting mated.
        if ev.score_mate > 0:
            return _MATE_CP - ev.score_mate
        return -_MATE_CP - ev.score_mate
    if ev.score_cp is not None:
        return ev.score_cp
    return 0


# Centipawn-loss thresholds (inclusive lower bounds).
_BLUNDER_THRESHOLD = 200
_MISTAKE_THRESHOLD = 100
_INACCURACY_THRESHOLD = 50


def _classify_move(
    cp_loss: int,
    is_best_move: bool,
    position_is_sharp: bool,
) -> MoveQuality:
    """Classify a move based on centipawn loss and context."""
    if is_best_move and position_is_sharp:
        return MoveQuality.BRILLIANT
    if cp_loss >= _BLUNDER_THRESHOLD:
        return MoveQuality.BLUNDER
    if cp_loss >= _MISTAKE_THRESHOLD:
        return MoveQuality.MISTAKE
    if cp_loss >= _INACCURACY_THRESHOLD:
        return MoveQuality.INACCURACY
    return MoveQuality.GOOD


def _move_to_san(board: chess.Board, uci: str) -> str:
    """Convert a UCI string to SAN notation, returning UCI on failure."""
    try:
        move = chess.Move.from_uci(uci)
        return board.san(move)
    except (ValueError, chess.IllegalMoveError, AssertionError):
        return uci


def _generate_message(
    quality: MoveQuality,
    player_move_san: str,
    best_move_san: str,
    cp_loss: int,
    is_best_move: bool,
    tactics_summary: str,
) -> str:
    """Build a human-readable coaching message."""
    parts: list[str] = []

    if quality == MoveQuality.BRILLIANT:
        parts.append(f"Excellent! {player_move_san} is the best move here.")
        if tactics_summary:
            parts.append(tactics_summary)
        return " ".join(parts)

    label = quality.value.capitalize()
    parts.append(f"{label}: {player_move_san} loses about {cp_loss / 100:.1f} pawns.")

    if not is_best_move:
        parts.append(f"The best move was {best_move_san}.")

    if tactics_summary:
        parts.append(tactics_summary)

    return " ".join(parts)


def _summarize_tactics(board: chess.Board, motifs: TacticalMotifs | None = None) -> str:
    """Return a short text summary of tactical motifs on *board*."""
    if motifs is None:
        motifs = analyze_tactics(board)
    pieces: list[str] = []

    if motifs.forks:
        fork = motifs.forks[0]
        targets = ", ".join(fork.targets)
        pieces.append(f"There is a fork on {fork.forking_square} targeting {targets}.")

    if motifs.hanging:
        for h in motifs.hanging:
            pieces.append(f"The {h.piece} on {h.square} is hanging.")

    if motifs.pins:
        pin = motifs.pins[0]
        pieces.append(
            f"The {pin.pinned_piece} on {pin.pinned_square} is pinned by "
            f"the {pin.pinner_piece} on {pin.pinner_square}."
        )

    if motifs.skewers:
        sk = motifs.skewers[0]
        pieces.append(
            f"There is a skewer: {sk.attacker_piece} on {sk.attacker_square} "
            f"attacks {sk.front_piece} on {sk.front_square} and "
            f"{sk.behind_piece} on {sk.behind_square}."
        )

    return " ".join(pieces)


def _build_arrows(
    quality: MoveQuality,
    player_move_uci: str,
    best_move_uci: str,
    is_best_move: bool,
    board_after: chess.Board,
    tactics: TacticalMotifs | None = None,
) -> list[Arrow]:
    """Create chessground arrow annotations."""
    arrows: list[Arrow] = []

    if quality == MoveQuality.BRILLIANT:
        # Show the brilliant move in blue.
        orig = player_move_uci[:2]
        dest = player_move_uci[2:4]
        arrows.append(Arrow(orig=orig, dest=dest, brush="blue"))
        # Also add tactical arrows from fork targets, etc.
        motifs = tactics if tactics is not None else analyze_tactics(board_after)
        for fork in motifs.forks:
            for target in fork.targets:
                arrows.append(Arrow(orig=fork.forking_square, dest=target, brush="yellow"))
        return arrows

    # For mistakes / blunders / inaccuracies show the player's move in red
    # and the best move in green.
    orig = player_move_uci[:2]
    dest = player_move_uci[2:4]
    arrows.append(Arrow(orig=orig, dest=dest, brush="red"))

    if not is_best_move and len(best_move_uci) >= 4:
        best_orig = best_move_uci[:2]
        best_dest = best_move_uci[2:4]
        arrows.append(Arrow(orig=best_orig, dest=best_dest, brush="green"))

    return arrows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assess_move(
    *,
    board_before: chess.Board,
    board_after: chess.Board,
    player_move_uci: str,
    eval_before: Evaluation,
    eval_after: Evaluation,
    best_move_uci: str,
    position_is_sharp: bool = False,
) -> CoachingResponse | None:
    """Assess a player's move and optionally return coaching feedback.

    Both *eval_before* and *eval_after* are expected to be from White's
    perspective (which is what ``engine.evaluate`` returns via
    ``score.white()``).

    Returns ``None`` when the move is routine and the coach should stay
    silent.
    """
    cp_before = _cp_value(eval_before)
    cp_after = _cp_value(eval_after)

    # Centipawn loss: how much the position worsened for the player.
    # Both evals are from White's POV. For White, losing means cp dropped.
    # For Black, losing means cp increased (better for White = worse for Black).
    if board_before.turn == chess.WHITE:
        cp_loss = cp_before - cp_after
    else:
        cp_loss = cp_after - cp_before

    is_best_move = player_move_uci == best_move_uci

    quality = _classify_move(cp_loss, is_best_move, position_is_sharp)

    # Coach stays silent for routine good moves.
    if quality == MoveQuality.GOOD:
        return None

    player_move_san = _move_to_san(board_before, player_move_uci)
    best_move_san = _move_to_san(board_before, best_move_uci)
    tactics = analyze_tactics(board_after)
    tactics_summary = _summarize_tactics(board_after, motifs=tactics)

    message = _generate_message(
        quality=quality,
        player_move_san=player_move_san,
        best_move_san=best_move_san,
        cp_loss=cp_loss,
        is_best_move=is_best_move,
        tactics_summary=tactics_summary,
    )

    arrows = _build_arrows(
        quality=quality,
        player_move_uci=player_move_uci,
        best_move_uci=best_move_uci,
        is_best_move=is_best_move,
        board_after=board_after,
        tactics=tactics,
    )

    severity = min(100, max(0, cp_loss))

    return CoachingResponse(
        quality=quality,
        message=message,
        arrows=arrows,
        severity=severity,
        tactics_summary=tactics_summary,
    )
