"""Open files, diagonals, pawn color complexes, and center control."""

from dataclasses import dataclass, field

import chess

from server.analysis.constants import CENTER_SQUARES, LONG_DIAGONALS, _color_name
from server.analysis.king_safety import _pawn_attacks_bb

__all__ = [
    "FileStatus",
    "DiagonalInfo",
    "PawnColorComplex",
    "FilesAndDiagonals",
    "SquareControl",
    "CenterControl",
    "_analyze_square_control",
    "analyze_files_and_diagonals",
    "analyze_center_control",
]


@dataclass
class FileStatus:
    file: int  # 0-7
    is_open: bool
    semi_open_white: bool  # no white pawns
    semi_open_black: bool  # no black pawns
    white_rooks: int = 0
    black_rooks: int = 0
    white_queen: bool = False
    black_queen: bool = False
    contested: bool = False        # both sides have major pieces on file
    white_controls: bool = False   # white has more major pieces on file
    black_controls: bool = False


@dataclass
class DiagonalInfo:
    name: str                    # "a1-h8" or "a8-h1"
    bishop_square: str | None    # square of bishop on this diagonal (if any)
    bishop_color: str | None     # "white" or "black"
    is_blocked: bool             # pawns obstruct the bishop's scope
    mobility: int                # squares the bishop can reach on this diagonal


@dataclass
class PawnColorComplex:
    white_pawns_light: int = 0
    white_pawns_dark: int = 0
    black_pawns_light: int = 0
    black_pawns_dark: int = 0
    white_has_light_bishop: bool = False
    white_has_dark_bishop: bool = False
    black_has_light_bishop: bool = False
    black_has_dark_bishop: bool = False
    white_weak_color: str | None = None  # "light" or "dark" if pawns + no bishop
    black_weak_color: str | None = None


@dataclass
class FilesAndDiagonals:
    files: list[FileStatus]
    rooks_on_open_files: list[str]  # square names
    rooks_on_semi_open_files: list[str]
    bishops_on_long_diagonals: list[str]
    connected_rooks_white: list[str] = field(default_factory=list)  # e.g. ["e1-e4"]
    connected_rooks_black: list[str] = field(default_factory=list)
    rooks_on_seventh: list[str] = field(default_factory=list)       # rooks on 7th/2nd rank
    long_diagonals: list[DiagonalInfo] = field(default_factory=list)
    pawn_color_complex: PawnColorComplex | None = None


def _find_connected_rooks(board: chess.Board, color: chess.Color) -> list[str]:
    """Find connected rook pairs: same rank or file, no pieces between."""
    rooks = list(board.pieces(chess.ROOK, color))
    pairs = []
    for i, r1 in enumerate(rooks):
        for r2 in rooks[i + 1:]:
            if chess.square_file(r1) == chess.square_file(r2) or chess.square_rank(r1) == chess.square_rank(r2):
                between = chess.between(r1, r2)
                if not (board.occupied & between):
                    pairs.append(f"{chess.square_name(r1)}-{chess.square_name(r2)}")
    return pairs


def _analyze_long_diagonal(board: chess.Board, diag_bb: int, diag_name: str) -> DiagonalInfo:
    """Analyze a long diagonal for bishop presence, blockage, and mobility."""
    bishop_sq = None
    bishop_color_str = None
    for color in (chess.WHITE, chess.BLACK):
        for sq in board.pieces(chess.BISHOP, color):
            if chess.BB_SQUARES[sq] & diag_bb:
                bishop_sq = chess.square_name(sq)
                bishop_color_str = _color_name(color)
                break
        if bishop_sq:
            break

    # Count pawns blocking the diagonal
    pawn_block = bool(
        (board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK)) & diag_bb
    )

    # Bishop mobility on this diagonal
    mobility = 0
    if bishop_sq is not None:
        sq_idx = chess.parse_square(bishop_sq)
        # Count squares bishop can reach on this diagonal
        reachable = board.attacks(sq_idx) & diag_bb
        mobility = len(chess.SquareSet(reachable))

    return DiagonalInfo(
        name=diag_name,
        bishop_square=bishop_sq,
        bishop_color=bishop_color_str,
        is_blocked=pawn_block,
        mobility=mobility,
    )


def _analyze_pawn_color_complex(board: chess.Board) -> PawnColorComplex:
    """Analyze pawn-color imbalance and weak square complexes."""
    wp_light = len(board.pieces(chess.PAWN, chess.WHITE) & chess.SquareSet(chess.BB_LIGHT_SQUARES))
    wp_dark = len(board.pieces(chess.PAWN, chess.WHITE) & chess.SquareSet(chess.BB_DARK_SQUARES))
    bp_light = len(board.pieces(chess.PAWN, chess.BLACK) & chess.SquareSet(chess.BB_LIGHT_SQUARES))
    bp_dark = len(board.pieces(chess.PAWN, chess.BLACK) & chess.SquareSet(chess.BB_DARK_SQUARES))

    w_light_bishop = bool(board.pieces(chess.BISHOP, chess.WHITE) & chess.BB_LIGHT_SQUARES)
    w_dark_bishop = bool(board.pieces(chess.BISHOP, chess.WHITE) & chess.BB_DARK_SQUARES)
    b_light_bishop = bool(board.pieces(chess.BISHOP, chess.BLACK) & chess.BB_LIGHT_SQUARES)
    b_dark_bishop = bool(board.pieces(chess.BISHOP, chess.BLACK) & chess.BB_DARK_SQUARES)

    # Weak color: pawns concentrated on one color AND missing bishop of that color
    w_weak = None
    if wp_light > wp_dark + 1 and not w_light_bishop:
        w_weak = "dark"   # pawns on light, no light bishop → dark squares weak
    elif wp_dark > wp_light + 1 and not w_dark_bishop:
        w_weak = "light"  # pawns on dark, no dark bishop → light squares weak

    b_weak = None
    if bp_light > bp_dark + 1 and not b_light_bishop:
        b_weak = "dark"
    elif bp_dark > bp_light + 1 and not b_dark_bishop:
        b_weak = "light"

    return PawnColorComplex(
        white_pawns_light=wp_light,
        white_pawns_dark=wp_dark,
        black_pawns_light=bp_light,
        black_pawns_dark=bp_dark,
        white_has_light_bishop=w_light_bishop,
        white_has_dark_bishop=w_dark_bishop,
        black_has_light_bishop=b_light_bishop,
        black_has_dark_bishop=b_dark_bishop,
        white_weak_color=w_weak,
        black_weak_color=b_weak,
    )


def analyze_files_and_diagonals(board: chess.Board) -> FilesAndDiagonals:
    file_statuses = []
    for f in range(8):
        file_bb = chess.BB_FILES[f]
        wp = bool(board.pieces(chess.PAWN, chess.WHITE) & file_bb)
        bp = bool(board.pieces(chess.PAWN, chess.BLACK) & file_bb)
        # Count major pieces on this file
        w_rooks = len(board.pieces(chess.ROOK, chess.WHITE) & chess.SquareSet(file_bb))
        b_rooks = len(board.pieces(chess.ROOK, chess.BLACK) & chess.SquareSet(file_bb))
        w_queen = bool(board.pieces(chess.QUEEN, chess.WHITE) & file_bb)
        b_queen = bool(board.pieces(chess.QUEEN, chess.BLACK) & file_bb)
        w_major = w_rooks + (1 if w_queen else 0)
        b_major = b_rooks + (1 if b_queen else 0)
        file_statuses.append(FileStatus(
            file=f,
            is_open=not wp and not bp,
            semi_open_white=not wp and bp,
            semi_open_black=wp and not bp,
            white_rooks=w_rooks,
            black_rooks=b_rooks,
            white_queen=w_queen,
            black_queen=b_queen,
            contested=w_major > 0 and b_major > 0,
            white_controls=w_major > b_major,
            black_controls=b_major > w_major,
        ))

    rooks_open = []
    rooks_semi = []
    rooks_seventh = []
    for color in (chess.WHITE, chess.BLACK):
        seventh_rank = 6 if color == chess.WHITE else 1
        for sq in board.pieces(chess.ROOK, color):
            f = chess.square_file(sq)
            fs = file_statuses[f]
            if fs.is_open:
                rooks_open.append(chess.square_name(sq))
            elif fs.semi_open_white if color == chess.WHITE else fs.semi_open_black:
                rooks_semi.append(chess.square_name(sq))
            if chess.square_rank(sq) == seventh_rank:
                rooks_seventh.append(chess.square_name(sq))

    bishops_long = []
    for color in (chess.WHITE, chess.BLACK):
        for sq in board.pieces(chess.BISHOP, color):
            sq_bb = chess.BB_SQUARES[sq]
            for diag in LONG_DIAGONALS:
                if sq_bb & diag:
                    bishops_long.append(chess.square_name(sq))
                    break

    # Long diagonal analysis
    diag_names = ["a1-h8", "a8-h1"]
    long_diag_infos = [
        _analyze_long_diagonal(board, LONG_DIAGONALS[i], diag_names[i])
        for i in range(2)
    ]

    return FilesAndDiagonals(
        files=file_statuses,
        rooks_on_open_files=rooks_open,
        rooks_on_semi_open_files=rooks_semi,
        bishops_on_long_diagonals=bishops_long,
        connected_rooks_white=_find_connected_rooks(board, chess.WHITE),
        connected_rooks_black=_find_connected_rooks(board, chess.BLACK),
        rooks_on_seventh=rooks_seventh,
        long_diagonals=long_diag_infos,
        pawn_color_complex=_analyze_pawn_color_complex(board),
    )


@dataclass
class SquareControl:
    square: str
    white_pawn_attacks: int
    white_piece_attacks: int
    black_pawn_attacks: int
    black_piece_attacks: int
    occupied_by: str | None  # e.g. "white_pawn", "black_knight", or None


_PIECE_TYPE_NAMES = {
    chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
    chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
}


def _analyze_square_control(board: chess.Board, sq: int, *, pin_aware: bool = True) -> SquareControl:
    """Count attackers of a square, split by color and pawn/piece."""
    wp, wpc, bp, bpc = 0, 0, 0, 0
    for attacker_sq in board.attackers(chess.WHITE, sq):
        if pin_aware and board.is_pinned(chess.WHITE, attacker_sq):
            pin_mask = board.pin(chess.WHITE, attacker_sq)
            if sq not in pin_mask:
                continue
        if board.piece_type_at(attacker_sq) == chess.PAWN:
            wp += 1
        else:
            wpc += 1
    for attacker_sq in board.attackers(chess.BLACK, sq):
        if pin_aware and board.is_pinned(chess.BLACK, attacker_sq):
            pin_mask = board.pin(chess.BLACK, attacker_sq)
            if sq not in pin_mask:
                continue
        if board.piece_type_at(attacker_sq) == chess.PAWN:
            bp += 1
        else:
            bpc += 1

    occupied_by = None
    piece = board.piece_at(sq)
    if piece is not None:
        color_name = "white" if piece.color == chess.WHITE else "black"
        type_name = _PIECE_TYPE_NAMES.get(piece.piece_type, "piece")
        occupied_by = f"{color_name}_{type_name}"

    return SquareControl(
        square=chess.square_name(sq),
        white_pawn_attacks=wp,
        white_piece_attacks=wpc,
        black_pawn_attacks=bp,
        black_piece_attacks=bpc,
        occupied_by=occupied_by,
    )


@dataclass
class CenterControl:
    squares: list[SquareControl]  # 4 entries: d4, e4, d5, e5
    white_total: int              # sum of all white attacks (pawn + piece)
    black_total: int              # sum of all black attacks (pawn + piece)


def analyze_center_control(board: chess.Board) -> CenterControl:
    sq_controls = [_analyze_square_control(board, sq) for sq in CENTER_SQUARES]
    white_total = sum(sc.white_pawn_attacks + sc.white_piece_attacks for sc in sq_controls)
    black_total = sum(sc.black_pawn_attacks + sc.black_piece_attacks for sc in sq_controls)
    return CenterControl(
        squares=sq_controls,
        white_total=white_total,
        black_total=black_total,
    )
