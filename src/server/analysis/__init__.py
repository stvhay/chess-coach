"""Pure-function position analysis package.

All functions take a chess.Board and return typed dataclass instances.
No Stockfish, no side effects. The LLM teacher uses these structured facts
instead of hallucinating about positions.
"""

from dataclasses import dataclass, field

import chess

# Re-export everything so `from server.analysis import X` still works
from server.analysis.constants import *  # noqa: F401,F403
from server.analysis.material import *  # noqa: F401,F403
from server.analysis.pawns import *  # noqa: F401,F403
from server.analysis.king_safety import *  # noqa: F401,F403
from server.analysis.activity import *  # noqa: F401,F403
from server.analysis.tactics import *  # noqa: F401,F403
from server.analysis.structure import *  # noqa: F401,F403
from server.analysis.positional import *  # noqa: F401,F403

# Explicit imports for orchestration logic
from server.analysis.constants import GamePhase, _color_name
from server.analysis.material import MaterialInfo, analyze_material
from server.analysis.pawns import PawnStructure, analyze_pawn_structure
from server.analysis.king_safety import KingSafety, analyze_king_safety
from server.analysis.activity import ActivityInfo, analyze_activity
from server.analysis.tactics import TacticValue, TacticalMotifs, analyze_tactics, index_by_piece, see
from server.analysis.structure import (
    CenterControl,
    FilesAndDiagonals,
    PawnColorComplex,
    analyze_center_control,
    analyze_files_and_diagonals,
)
from server.analysis.positional import (
    Development,
    Space,
    _count_developed,
    analyze_development,
    analyze_space,
)


@dataclass
class PositionReport:
    fen: str
    turn: str
    fullmove_number: int
    is_check: bool
    is_checkmate: bool
    is_stalemate: bool
    material: MaterialInfo
    pawn_structure: PawnStructure
    king_safety_white: KingSafety
    king_safety_black: KingSafety
    activity: ActivityInfo
    tactics: TacticalMotifs
    files_and_diagonals: FilesAndDiagonals
    center_control: CenterControl
    development: Development
    space: Space
    phase: str = ""  # "opening", "middlegame", "endgame"
    piece_index: dict = field(default_factory=dict)


def _empty_activity() -> ActivityInfo:
    """Zero-valued ActivityInfo for terminal positions."""
    return ActivityInfo(white=[], black=[], white_total_mobility=0, black_total_mobility=0)


def _empty_space() -> Space:
    """Zero-valued Space for terminal positions."""
    return Space(white_squares=0, black_squares=0, white_occupied=0, black_occupied=0)


def _empty_center_control() -> CenterControl:
    """Zero-valued CenterControl for terminal positions."""
    return CenterControl(squares=[], white_total=0, black_total=0)


def _empty_development() -> Development:
    """Zero-valued Development for terminal positions."""
    return Development(white_developed=0, black_developed=0, white_castled="none", black_castled="none")


def _empty_files_and_diagonals() -> FilesAndDiagonals:
    """Empty FilesAndDiagonals for terminal positions."""
    return FilesAndDiagonals(
        files=[], rooks_on_open_files=[], rooks_on_semi_open_files=[],
        bishops_on_long_diagonals=[], pawn_color_complex=PawnColorComplex(),
    )


def detect_game_phase(board: chess.Board) -> GamePhase:
    """Detect the current game phase from board state.

    Opening: move <= 15 AND (either side < 3 minors developed OR no captures)
    Endgame: no queens OR both sides <= 13 material points
    Middlegame: everything else
    """
    mat = analyze_material(board)

    # Endgame: no queens on the board, or both sides have low material
    if mat.white.queens == 0 and mat.black.queens == 0:
        return GamePhase.ENDGAME
    if mat.white_total <= 13 and mat.black_total <= 13:
        return GamePhase.ENDGAME

    # Opening: early moves with undeveloped pieces
    if board.fullmove_number <= 15:
        w_dev = _count_developed(board, chess.WHITE)
        b_dev = _count_developed(board, chess.BLACK)
        if w_dev < 3 or b_dev < 3:
            return GamePhase.OPENING

    return GamePhase.MIDDLEGAME


def analyze(board: chess.Board) -> PositionReport:
    tactics = analyze_tactics(board)
    ks_w = analyze_king_safety(board, chess.WHITE)
    ks_b = analyze_king_safety(board, chess.BLACK)
    is_terminal = board.is_checkmate() or board.is_stalemate()
    phase = detect_game_phase(board)
    return PositionReport(
        fen=board.fen(),
        turn=_color_name(board.turn),
        fullmove_number=board.fullmove_number,
        is_check=board.is_check(),
        is_checkmate=board.is_checkmate(),
        is_stalemate=board.is_stalemate(),
        material=analyze_material(board),
        pawn_structure=analyze_pawn_structure(board),
        king_safety_white=ks_w,
        king_safety_black=ks_b,
        activity=_empty_activity() if is_terminal else analyze_activity(board, phase),
        tactics=tactics,
        files_and_diagonals=_empty_files_and_diagonals() if is_terminal else analyze_files_and_diagonals(board),
        center_control=_empty_center_control() if is_terminal else analyze_center_control(board),
        development=_empty_development() if is_terminal else analyze_development(board, ks_w, ks_b),
        space=_empty_space() if is_terminal else analyze_space(board),
        phase=phase.value,
        piece_index=index_by_piece(tactics),
    )
