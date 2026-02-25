"""King safety analysis: pawn shield, open files, danger scoring."""

from dataclasses import dataclass, field

import chess

__all__ = [
    "KingSafety",
    "_pawn_attacks_bb",
    "analyze_king_safety",
]


@dataclass
class KingSafety:
    king_square: str | None
    # TODO(audit#6): castled is a development concept, not king safety. The
    # coupling exists because analyze_development() reads KingSafety.castled.
    # Both KingSafety and Development are stubs that will be replaced by
    # Stockfish-backed evaluations — defer refactoring until then.
    castled: str  # "kingside", "queenside", "none"
    has_kingside_castling_rights: bool
    has_queenside_castling_rights: bool
    pawn_shield_count: int
    pawn_shield_squares: list[str]
    open_files_near_king: list[int]
    semi_open_files_near_king: list[int]
    # King danger features:
    king_zone_attacks: int = 0
    weak_squares: int = 0
    safe_checks: dict = field(default_factory=dict)
    pawn_storm: int = 0
    pawn_shelter: int = 0
    knight_defender: bool = False
    queen_absent: bool = False
    danger_score: int = 0


_CASTLED_POSITIONS = {
    chess.G1: "kingside", chess.H1: "kingside",
    chess.C1: "queenside", chess.B1: "queenside",
    chess.G8: "kingside", chess.H8: "kingside",
    chess.C8: "queenside", chess.B8: "queenside",
}


def _pawn_attacks_bb(board: chess.Board, color: chess.Color) -> int:
    """Return bitboard of all squares attacked by pawns of the given color."""
    pawns = board.pieces_mask(chess.PAWN, color)
    if color == chess.WHITE:
        # White pawns attack diagonally upward
        left = (pawns & ~chess.BB_FILE_A) << 7
        right = (pawns & ~chess.BB_FILE_H) << 9
    else:
        # Black pawns attack diagonally downward
        left = (pawns & ~chess.BB_FILE_H) >> 7
        right = (pawns & ~chess.BB_FILE_A) >> 9
    return (left | right) & chess.BB_ALL


def analyze_king_safety(board: chess.Board, color: chess.Color) -> KingSafety:
    king_sq = board.king(color)
    if king_sq is None:
        return KingSafety(
            king_square=None,
            castled="none",
            has_kingside_castling_rights=False,
            has_queenside_castling_rights=False,
            pawn_shield_count=0,
            pawn_shield_squares=[],
            open_files_near_king=[],
            semi_open_files_near_king=[],
        )

    enemy = not color
    king_file = chess.square_file(king_sq)
    king_rank = chess.square_rank(king_sq)

    # --- Existing: castled heuristic ---
    castled = _CASTLED_POSITIONS.get(king_sq, "none")

    # --- Existing: pawn shield ---
    shield_squares = []
    shield_files = [f for f in (king_file - 1, king_file, king_file + 1) if 0 <= f <= 7]
    for sf in shield_files:
        for rank_offset in (1, 2):
            if color == chess.WHITE:
                sr = king_rank + rank_offset
            else:
                sr = king_rank - rank_offset
            if 0 <= sr <= 7:
                ssq = chess.square(sf, sr)
                piece = board.piece_at(ssq)
                if piece and piece.piece_type == chess.PAWN and piece.color == color:
                    shield_squares.append(chess.square_name(ssq))

    # --- Existing: open/semi-open files ---
    open_files = []
    semi_open = []
    for sf in shield_files:
        file_bb = chess.BB_FILES[sf]
        white_pawns = bool(board.pieces(chess.PAWN, chess.WHITE) & file_bb)
        black_pawns = bool(board.pieces(chess.PAWN, chess.BLACK) & file_bb)
        if not white_pawns and not black_pawns:
            open_files.append(sf)
        elif color == chess.WHITE and not white_pawns:
            semi_open.append(sf)
        elif color == chess.BLACK and not black_pawns:
            semi_open.append(sf)

    # --- NEW: king ring (8 surrounding squares + king square) ---
    king_ring = chess.SquareSet(board.attacks_mask(king_sq)) | chess.SquareSet(
        chess.BB_SQUARES[king_sq]
    )

    # --- NEW: king_zone_attacks ---
    # Count enemy non-pawn piece attacks on king ring squares
    zone_attacks = 0
    for sq in king_ring:
        for attacker_sq in board.attackers(enemy, sq):
            attacker = board.piece_at(attacker_sq)
            if attacker and attacker.piece_type != chess.PAWN:
                zone_attacks += 1

    # --- NEW: weak_squares ---
    # King zone squares attacked by enemy but not defended by own pawns
    own_pawn_attacks = chess.SquareSet(_pawn_attacks_bb(board, color))
    weak = 0
    for sq in king_ring:
        if board.attackers(enemy, sq) and sq not in own_pawn_attacks:
            weak += 1

    # --- NEW: safe_checks ---
    # For each piece type, count enemy pieces that can move to a square
    # giving check where the destination is not defended by our pieces.
    safe = {"knight": 0, "bishop": 0, "rook": 0, "queen": 0}
    _name_map = {
        chess.KNIGHT: "knight",
        chess.BISHOP: "bishop",
        chess.ROOK: "rook",
        chess.QUEEN: "queen",
    }
    if enemy == board.turn:
        # Enemy has the move -- use legal_moves directly
        for move in board.legal_moves:
            piece = board.piece_at(move.from_square)
            if piece is None:
                continue
            pt = piece.piece_type
            if pt not in _name_map:
                continue
            board.push(move)
            if board.is_check() and not board.attackers(color, move.to_square):
                safe[_name_map[pt]] += 1
            board.pop()
    else:
        # We have the move -- use null move to see enemy's perspective
        board.push(chess.Move.null())
        if not board.is_check():
            for move in board.legal_moves:
                piece = board.piece_at(move.from_square)
                if piece is None:
                    continue
                pt = piece.piece_type
                if pt not in _name_map:
                    continue
                board.push(move)
                if board.is_check() and not board.attackers(color, move.to_square):
                    safe[_name_map[pt]] += 1
                board.pop()
        board.pop()

    # --- NEW: pawn_storm ---
    # Count enemy pawns advancing toward king on nearby files
    storm = 0
    for sf in shield_files:
        for pawn_sq in board.pieces(chess.PAWN, enemy):
            if chess.square_file(pawn_sq) == sf:
                pawn_rank = chess.square_rank(pawn_sq)
                distance = pawn_rank if color == chess.WHITE else 7 - pawn_rank
                if distance <= 4:
                    storm += 5 - distance

    # --- NEW: pawn_shelter ---
    # Count own pawns on rank immediately ahead on king file +/- 1
    shelter = 0
    ahead_rank = king_rank + 1 if color == chess.WHITE else king_rank - 1
    if 0 <= ahead_rank <= 7:
        for sf in shield_files:
            ssq = chess.square(sf, ahead_rank)
            piece = board.piece_at(ssq)
            if piece and piece.piece_type == chess.PAWN and piece.color == color:
                shelter += 1

    # --- NEW: knight_defender ---
    has_knight_defender = False
    for knight_sq in board.pieces(chess.KNIGHT, color):
        if knight_sq in king_ring:
            has_knight_defender = True
            break

    # --- NEW: queen_absent ---
    enemy_queen_absent = not bool(board.pieces(chess.QUEEN, enemy))

    # --- NEW: danger_score ---
    danger = (
        zone_attacks * 20
        + weak * 30
        + sum(safe.values()) * 25
        + storm * 15
        - shelter * 20
        - (40 if has_knight_defender else 0)
        - (200 if enemy_queen_absent else 0)
    )

    return KingSafety(
        king_square=chess.square_name(king_sq),
        castled=castled,
        has_kingside_castling_rights=board.has_kingside_castling_rights(color),
        has_queenside_castling_rights=board.has_queenside_castling_rights(color),
        pawn_shield_count=len(shield_squares),
        pawn_shield_squares=shield_squares,
        open_files_near_king=open_files,
        semi_open_files_near_king=semi_open,
        king_zone_attacks=zone_attacks,
        weak_squares=weak,
        safe_checks=safe,
        pawn_storm=storm,
        pawn_shelter=shelter,
        knight_defender=has_knight_defender,
        queen_absent=enemy_queen_absent,
        danger_score=danger,
    )
