"""Pure-function position analysis module.

All functions take a chess.Board and return typed dataclass instances.
No Stockfish, no side effects. The LLM teacher uses these structured facts
instead of hallucinating about positions.
"""

from dataclasses import dataclass, field

import chess

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CENTER_SQUARES = [chess.D4, chess.E4, chess.D5, chess.E5]

def get_piece_value(piece_type: chess.PieceType, *, king=None) -> int:
    """Get standard piece value. King value must be explicitly provided.

    king=None (default) causes TypeError if caller forgets to handle king,
    which is the desired behavior — forces explicit handling.
    """
    return {
        chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
        chess.ROOK: 5, chess.QUEEN: 9, chess.KING: king,
    }[piece_type]


# Shared field mapping for MaterialCount ↔ piece values
_PIECE_FIELDS: list[tuple[str, chess.PieceType, int]] = [
    ("pawns", chess.PAWN, 1),
    ("knights", chess.KNIGHT, 3),
    ("bishops", chess.BISHOP, 3),
    ("rooks", chess.ROOK, 5),
    ("queens", chess.QUEEN, 9),
]

def _colored(piece_char: str) -> str:
    """Add color prefix: 'N' → 'White N', 'p' → 'Black P'."""
    color = "White" if piece_char.isupper() else "Black"
    return f"{color} {piece_char.upper()}"


def _color_name(color: chess.Color) -> str:
    """Convert chess.Color bool to lowercase string."""
    return "white" if color == chess.WHITE else "black"


STARTING_MINORS = {
    chess.WHITE: [
        (chess.B1, chess.KNIGHT),
        (chess.G1, chess.KNIGHT),
        (chess.C1, chess.BISHOP),
        (chess.F1, chess.BISHOP),
    ],
    chess.BLACK: [
        (chess.B8, chess.KNIGHT),
        (chess.G8, chess.KNIGHT),
        (chess.C8, chess.BISHOP),
        (chess.F8, chess.BISHOP),
    ],
}

LONG_DIAGONALS = [
    chess.BB_A1 | chess.BB_B2 | chess.BB_C3 | chess.BB_D4 | chess.BB_E5 | chess.BB_F6 | chess.BB_G7 | chess.BB_H8,
    chess.BB_A8 | chess.BB_B7 | chess.BB_C6 | chess.BB_D5 | chess.BB_E4 | chess.BB_F3 | chess.BB_G2 | chess.BB_H1,
]

# ---------------------------------------------------------------------------
# 1. Material
# ---------------------------------------------------------------------------


@dataclass
class MaterialCount:
    pawns: int = 0
    knights: int = 0
    bishops: int = 0
    rooks: int = 0
    queens: int = 0


@dataclass
class MaterialInfo:
    white: MaterialCount
    black: MaterialCount
    white_total: int
    black_total: int
    imbalance: int  # white_total - black_total
    white_bishop_pair: bool
    black_bishop_pair: bool


def _count_material(board: chess.Board, color: chess.Color) -> MaterialCount:
    return MaterialCount(
        pawns=len(board.pieces(chess.PAWN, color)),
        knights=len(board.pieces(chess.KNIGHT, color)),
        bishops=len(board.pieces(chess.BISHOP, color)),
        rooks=len(board.pieces(chess.ROOK, color)),
        queens=len(board.pieces(chess.QUEEN, color)),
    )


def _material_total(mc: MaterialCount) -> int:
    return sum(getattr(mc, fname) * val for fname, _, val in _PIECE_FIELDS)


def analyze_material(board: chess.Board) -> MaterialInfo:
    wc = _count_material(board, chess.WHITE)
    bc = _count_material(board, chess.BLACK)
    wt = _material_total(wc)
    bt = _material_total(bc)
    return MaterialInfo(
        white=wc,
        black=bc,
        white_total=wt,
        black_total=bt,
        imbalance=wt - bt,
        white_bishop_pair=(
            bool(board.pieces(chess.BISHOP, chess.WHITE) & chess.BB_LIGHT_SQUARES)
            and bool(board.pieces(chess.BISHOP, chess.WHITE) & chess.BB_DARK_SQUARES)
        ),
        black_bishop_pair=(
            bool(board.pieces(chess.BISHOP, chess.BLACK) & chess.BB_LIGHT_SQUARES)
            and bool(board.pieces(chess.BISHOP, chess.BLACK) & chess.BB_DARK_SQUARES)
        ),
    )


# ---------------------------------------------------------------------------
# 2. Pawn Structure
# ---------------------------------------------------------------------------


@dataclass
class PawnDetail:
    square: str
    is_isolated: bool = False
    is_doubled: bool = False
    is_passed: bool = False
    is_backward: bool = False
    is_chain_base: bool = False
    is_chain_member: bool = False


@dataclass
class PawnStructure:
    white: list[PawnDetail] = field(default_factory=list)
    black: list[PawnDetail] = field(default_factory=list)
    white_islands: int = 0
    black_islands: int = 0


@dataclass
class _FilePawnInfo:
    """Per-file pawn data for one color."""
    white_ranks: list[int]  # ranks of white pawns on this file (sorted)
    black_ranks: list[int]  # ranks of black pawns on this file (sorted)


def _build_file_pawn_info(board: chess.Board) -> list[_FilePawnInfo]:
    """Pass 1: Build per-file pawn data for both colors."""
    files = []
    for f in range(8):
        file_bb = chess.BB_FILES[f]
        w_pawns = board.pieces(chess.PAWN, chess.WHITE) & file_bb
        b_pawns = board.pieces(chess.PAWN, chess.BLACK) & file_bb
        files.append(_FilePawnInfo(
            white_ranks=sorted(chess.square_rank(sq) for sq in w_pawns),
            black_ranks=sorted(chess.square_rank(sq) for sq in b_pawns),
        ))
    return files


def _count_islands(file_info: list[_FilePawnInfo], color: chess.Color) -> int:
    """Count pawn islands from file info."""
    occupied = []
    for f in range(8):
        ranks = file_info[f].white_ranks if color == chess.WHITE else file_info[f].black_ranks
        if ranks:
            occupied.append(f)
    if not occupied:
        return 0
    islands = 1
    for i in range(1, len(occupied)):
        if occupied[i] > occupied[i - 1] + 1:
            islands += 1
    return islands


def _annotate_pawns(
    board: chess.Board,
    color: chess.Color,
    file_info: list[_FilePawnInfo],
) -> list[PawnDetail]:
    """Pass 2: Annotate each pawn using precomputed file data."""
    enemy = not color
    direction = 1 if color == chess.WHITE else -1  # pawn advance direction

    def _own(f: int) -> list[int]:
        return file_info[f].white_ranks if color == chess.WHITE else file_info[f].black_ranks

    def _enemy(f: int) -> list[int]:
        return file_info[f].black_ranks if color == chess.WHITE else file_info[f].white_ranks

    details = []
    for sq in board.pieces(chess.PAWN, color):
        f = chess.square_file(sq)
        r = chess.square_rank(sq)

        # Doubled: more than one own pawn on this file
        is_doubled = len(_own(f)) > 1

        # Isolated: no own pawns on adjacent files
        is_isolated = True
        for af in (f - 1, f + 1):
            if 0 <= af <= 7 and _own(af):
                is_isolated = False
                break

        # Passed: no enemy pawns on same or adjacent files ahead
        is_passed = True
        for cf in range(max(0, f - 1), min(8, f + 2)):
            for er in _enemy(cf):
                if (er - r) * direction > 0:  # enemy pawn is ahead
                    is_passed = False
                    break
            if not is_passed:
                break

        # Backward: stop square attacked by enemy pawn, no friendly pawn on adj files at or behind
        is_backward = False
        stop_rank = r + direction
        if 0 <= stop_rank <= 7:
            stop_sq = chess.square(f, stop_rank)
            enemy_pawn_attackers = board.attackers(enemy, stop_sq) & board.pieces(chess.PAWN, enemy)
            if enemy_pawn_attackers:
                is_backward = True
                for af in (f - 1, f + 1):
                    if 0 <= af <= 7:
                        if any((r - fr) * direction >= 0 for fr in _own(af)):
                            is_backward = False
                            break

        # Chain member: friendly pawn diagonally behind
        is_chain_member = False
        behind_rank = r - direction
        if 0 <= behind_rank <= 7:
            for af in (f - 1, f + 1):
                if 0 <= af <= 7 and behind_rank in _own(af):
                    is_chain_member = True
                    break

        # Chain base: not a chain member, but supports a pawn ahead
        is_chain_base = False
        if not is_chain_member:
            ahead_rank = r + direction
            if 0 <= ahead_rank <= 7:
                for af in (f - 1, f + 1):
                    if 0 <= af <= 7 and ahead_rank in _own(af):
                        is_chain_base = True
                        break

        details.append(PawnDetail(
            square=chess.square_name(sq),
            is_isolated=is_isolated,
            is_doubled=is_doubled,
            is_passed=is_passed,
            is_backward=is_backward,
            is_chain_base=is_chain_base,
            is_chain_member=is_chain_member,
        ))
    return details


def analyze_pawn_structure(board: chess.Board) -> PawnStructure:
    file_info = _build_file_pawn_info(board)
    return PawnStructure(
        white=_annotate_pawns(board, chess.WHITE, file_info),
        black=_annotate_pawns(board, chess.BLACK, file_info),
        white_islands=_count_islands(file_info, chess.WHITE),
        black_islands=_count_islands(file_info, chess.BLACK),
    )


# ---------------------------------------------------------------------------
# 3. King Safety
# ---------------------------------------------------------------------------


@dataclass
class KingSafety:
    king_square: str | None
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
    _CASTLED = {
        chess.G1: "kingside", chess.H1: "kingside",
        chess.C1: "queenside", chess.B1: "queenside",
        chess.G8: "kingside", chess.H8: "kingside",
        chess.C8: "queenside", chess.B8: "queenside",
    }
    castled = _CASTLED.get(king_sq, "none")

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
    own_pawn_attacks = chess.SquareSet()
    for pawn_sq in board.pieces(chess.PAWN, color):
        own_pawn_attacks |= board.attacks(pawn_sq)
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
                if color == chess.WHITE:
                    # Enemy (black) pawns advancing down -- rank closer to 0 is dangerous
                    distance = pawn_rank
                    if distance <= 4:
                        storm += 5 - distance
                else:
                    # Enemy (white) pawns advancing up -- rank closer to 7 is dangerous
                    distance = 7 - pawn_rank
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


# ---------------------------------------------------------------------------
# 4. Piece Activity
# ---------------------------------------------------------------------------


@dataclass
class PieceActivity:
    square: str
    piece: str  # e.g. "N", "b"
    mobility: int
    centralization: int  # min distance to center squares


@dataclass
class ActivityInfo:
    white: list[PieceActivity]
    black: list[PieceActivity]
    white_total_mobility: int
    black_total_mobility: int


def analyze_activity(board: chess.Board) -> ActivityInfo:
    white_pieces: list[PieceActivity] = []
    black_pieces: list[PieceActivity] = []

    for color in (chess.WHITE, chess.BLACK):
        own_occupied = board.occupied_co[color]
        piece_list = white_pieces if color == chess.WHITE else black_pieces

        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            for sq in board.pieces(pt, color):
                mobility = len(chess.SquareSet(board.attacks_mask(sq) & ~own_occupied))
                cent = min(chess.square_distance(sq, c) for c in CENTER_SQUARES)
                symbol = chess.Piece(pt, color).symbol()
                piece_list.append(PieceActivity(
                    square=chess.square_name(sq),
                    piece=symbol,
                    mobility=mobility,
                    centralization=cent,
                ))

    return ActivityInfo(
        white=white_pieces,
        black=black_pieces,
        white_total_mobility=sum(p.mobility for p in white_pieces),
        black_total_mobility=sum(p.mobility for p in black_pieces),
    )


# ---------------------------------------------------------------------------
# 5. Tactical Motifs
# ---------------------------------------------------------------------------


@dataclass
class Pin:
    pinned_square: str
    pinned_piece: str
    pinner_square: str
    pinner_piece: str
    pinned_to: str  # square of the piece being shielded (king, queen, etc.)
    pinned_to_piece: str = ""  # piece symbol on pinned_to square (e.g. "K", "q")
    is_absolute: bool = False  # pinned to king (piece cannot legally move)
    color: str = ""  # "white" or "black" — color of the pinner


@dataclass
class Fork:
    forking_square: str
    forking_piece: str
    targets: list[str]  # squares being forked
    target_pieces: list[str] = field(default_factory=list)  # piece chars on target squares
    color: str = ""  # "white" or "black" — color of the forking piece
    is_check_fork: bool = False   # one target is the king
    is_royal_fork: bool = False   # targets include both king and queen


@dataclass
class Skewer:
    attacker_square: str
    attacker_piece: str
    front_square: str
    front_piece: str
    behind_square: str
    behind_piece: str
    color: str = ""  # "white" or "black" — color of the attacker
    is_absolute: bool = False  # True when front piece is the king


@dataclass
class HangingPiece:
    square: str
    piece: str
    attacker_squares: list[str]
    color: str = ""  # "white" or "black" — whose piece is hanging
    can_retreat: bool = True  # piece owner moves next and can save it


@dataclass
class DiscoveredAttack:
    blocker_square: str
    blocker_piece: str
    slider_square: str
    slider_piece: str
    target_square: str
    target_piece: str
    significance: str = "normal"  # "low" for pawn-reveals-rook x-rays, "normal" otherwise
    color: str = ""  # "white" or "black" — color of the attacking side (slider owner)


@dataclass
class DoubleCheck:
    checker_squares: list[str]
    color: str = ""  # "white" or "black" — color of the checking side


@dataclass
class TrappedPiece:
    square: str
    piece: str
    color: str = ""  # "white" or "black" — color of the trapped piece


@dataclass
class MatePattern:
    pattern: str  # e.g. "back_rank", "smothered", "arabian", "hook", etc.


@dataclass
class MateThreat:
    threatening_color: str  # "white" or "black"
    mating_square: str      # square where mate would be delivered


@dataclass
class BackRankWeakness:
    weak_color: str  # "white" or "black" — whose back rank is vulnerable
    king_square: str


@dataclass
class XRayAttack:
    slider_square: str
    slider_piece: str
    through_square: str  # enemy piece being x-rayed through
    through_piece: str
    target_square: str   # valuable target behind
    target_piece: str
    color: str = ""  # "white" or "black" — color of the slider


@dataclass
class XRayDefense:
    slider_square: str
    slider_piece: str
    through_square: str   # enemy piece between slider and defended piece
    through_piece: str
    defended_square: str   # friendly piece being defended through the enemy
    defended_piece: str
    color: str = ""  # "white" or "black" — color of the slider


@dataclass
class ExposedKing:
    color: str  # "white" or "black" — whose king is exposed
    king_square: str


@dataclass
class OverloadedPiece:
    square: str
    piece: str
    defended_squares: list[str]  # attacked targets this piece sole-defends
    color: str = ""  # "white" or "black" — color of the overloaded piece


@dataclass
class CapturableDefender:
    defender_square: str
    defender_piece: str
    charge_square: str   # piece being defended
    charge_piece: str
    attacker_square: str  # who can capture the defender
    color: str = ""  # "white" or "black" — color of the defender


@dataclass
class TacticalMotifs:
    pins: list[Pin] = field(default_factory=list)
    forks: list[Fork] = field(default_factory=list)
    skewers: list[Skewer] = field(default_factory=list)
    hanging: list[HangingPiece] = field(default_factory=list)
    discovered_attacks: list[DiscoveredAttack] = field(default_factory=list)
    double_checks: list[DoubleCheck] = field(default_factory=list)
    trapped_pieces: list[TrappedPiece] = field(default_factory=list)
    mate_patterns: list[MatePattern] = field(default_factory=list)
    mate_threats: list[MateThreat] = field(default_factory=list)
    back_rank_weaknesses: list[BackRankWeakness] = field(default_factory=list)
    xray_attacks: list[XRayAttack] = field(default_factory=list)
    xray_defenses: list[XRayDefense] = field(default_factory=list)
    exposed_kings: list[ExposedKing] = field(default_factory=list)
    overloaded_pieces: list[OverloadedPiece] = field(default_factory=list)
    capturable_defenders: list[CapturableDefender] = field(default_factory=list)


@dataclass
class _RayMotifs:
    """Internal result container for unified ray detection."""
    pins: list[Pin]
    skewers: list[Skewer]
    xray_attacks: list[XRayAttack]
    xray_defenses: list[XRayDefense]
    discovered_attacks: list[DiscoveredAttack]


_ORTHOGONAL = [(0, 1), (0, -1), (1, 0), (-1, 0)]
_DIAGONAL = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

_RAY_DIRS: dict[chess.PieceType, list[tuple[int, int]]] = {
    chess.ROOK: _ORTHOGONAL,
    chess.BISHOP: _DIAGONAL,
    chess.QUEEN: _ORTHOGONAL + _DIAGONAL,
}


def _walk_ray(
    board: chess.Board,
    start_sq: int,
    direction: tuple[int, int],
) -> tuple[int | None, int | None]:
    """Walk a ray from start_sq, return (first_hit_sq, second_hit_sq) or None."""
    df, dr = direction
    f = chess.square_file(start_sq) + df
    r = chess.square_rank(start_sq) + dr
    first = None
    while 0 <= f <= 7 and 0 <= r <= 7:
        sq = chess.square(f, r)
        if board.piece_at(sq) is not None:
            if first is None:
                first = sq
            else:
                return first, sq
        f += df
        r += dr
    return first, None


def _find_ray_motifs(board: chess.Board) -> _RayMotifs:
    """Single-pass ray analysis producing pins, skewers, x-rays, discovered attacks.

    For each slider, walk each ray direction. When two pieces are found along
    the ray, classify by the colors and values of the intervening and beyond pieces.
    """
    pins: list[Pin] = []
    skewers: list[Skewer] = []
    xray_attacks: list[XRayAttack] = []
    xray_defenses: list[XRayDefense] = []
    discovered: list[DiscoveredAttack] = []

    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        color_name = _color_name(color)

        for pt in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            for slider_sq in board.pieces(pt, color):
                slider_piece = board.piece_at(slider_sq)
                if slider_piece is None:
                    continue

                for direction in _RAY_DIRS[pt]:
                    first_sq, second_sq = _walk_ray(board, slider_sq, direction)
                    if first_sq is None or second_sq is None:
                        continue

                    first_piece = board.piece_at(first_sq)
                    second_piece = board.piece_at(second_sq)
                    if first_piece is None or second_piece is None:
                        continue

                    first_color = first_piece.color
                    second_color = second_piece.color

                    if first_color == enemy and second_color == enemy:
                        # Both enemy: pin, skewer, or x-ray attack
                        first_val = get_piece_value(first_piece.piece_type, king=1000)
                        second_val = get_piece_value(second_piece.piece_type, king=1000)

                        if second_piece.piece_type == chess.KING:
                            # Absolute pin
                            pins.append(Pin(
                                pinned_square=chess.square_name(first_sq),
                                pinned_piece=first_piece.symbol(),
                                pinner_square=chess.square_name(slider_sq),
                                pinner_piece=slider_piece.symbol(),
                                pinned_to=chess.square_name(second_sq),
                                pinned_to_piece=second_piece.symbol(),
                                is_absolute=True,
                                color=color_name,
                            ))
                        elif first_val < second_val:
                            # Relative pin — lower value pinned to higher value
                            pins.append(Pin(
                                pinned_square=chess.square_name(first_sq),
                                pinned_piece=first_piece.symbol(),
                                pinner_square=chess.square_name(slider_sq),
                                pinner_piece=slider_piece.symbol(),
                                pinned_to=chess.square_name(second_sq),
                                pinned_to_piece=second_piece.symbol(),
                                is_absolute=False,
                                color=color_name,
                            ))
                        elif first_piece.piece_type == chess.KING:
                            # Absolute skewer — king must move
                            skewers.append(Skewer(
                                attacker_square=chess.square_name(slider_sq),
                                attacker_piece=slider_piece.symbol(),
                                front_square=chess.square_name(first_sq),
                                front_piece=first_piece.symbol(),
                                behind_square=chess.square_name(second_sq),
                                behind_piece=second_piece.symbol(),
                                color=color_name,
                                is_absolute=True,
                            ))
                        elif first_val > second_val:
                            # Skewer — higher value forced to move
                            skewers.append(Skewer(
                                attacker_square=chess.square_name(slider_sq),
                                attacker_piece=slider_piece.symbol(),
                                front_square=chess.square_name(first_sq),
                                front_piece=first_piece.symbol(),
                                behind_square=chess.square_name(second_sq),
                                behind_piece=second_piece.symbol(),
                                color=color_name,
                                is_absolute=False,
                            ))
                        else:
                            # Equal or lower front value, beyond not king = x-ray attack
                            xray_attacks.append(XRayAttack(
                                slider_square=chess.square_name(slider_sq),
                                slider_piece=slider_piece.symbol(),
                                through_square=chess.square_name(first_sq),
                                through_piece=first_piece.symbol(),
                                target_square=chess.square_name(second_sq),
                                target_piece=second_piece.symbol(),
                                color=color_name,
                            ))

                    elif first_color == enemy and second_color == color:
                        # Enemy then friendly = x-ray defense
                        xray_defenses.append(XRayDefense(
                            slider_square=chess.square_name(slider_sq),
                            slider_piece=slider_piece.symbol(),
                            through_square=chess.square_name(first_sq),
                            through_piece=first_piece.symbol(),
                            defended_square=chess.square_name(second_sq),
                            defended_piece=second_piece.symbol(),
                            color=color_name,
                        ))

                    elif first_color == color and second_color == enemy:
                        # Friendly then enemy = potential discovered attack
                        # Significance based on target type
                        sig = "normal"
                        if second_piece.piece_type == chess.KING:
                            sig = "check"
                        elif (first_piece.piece_type == chess.PAWN
                              and pt == chess.ROOK
                              and get_piece_value(second_piece.piece_type, king=0) <= 1):
                            sig = "low"
                        discovered.append(DiscoveredAttack(
                            blocker_square=chess.square_name(first_sq),
                            blocker_piece=first_piece.symbol(),
                            slider_square=chess.square_name(slider_sq),
                            slider_piece=slider_piece.symbol(),
                            target_square=chess.square_name(second_sq),
                            target_piece=second_piece.symbol(),
                            significance=sig,
                            color=color_name,
                        ))

    return _RayMotifs(
        pins=pins, skewers=skewers, xray_attacks=xray_attacks,
        xray_defenses=xray_defenses, discovered_attacks=discovered,
    )


def _find_forks(board: chess.Board) -> list[Fork]:
    forks = []
    for color in (chess.WHITE, chess.BLACK):
        color_name = _color_name(color)
        enemy = not color
        for sq in chess.SquareSet(board.occupied_co[color]):
            piece = board.piece_at(sq)
            if piece is None:
                continue

            attacks = board.attacks(sq)
            targets = []
            target_pieces = []
            target_types = []
            for target_sq in attacks:
                target_piece = board.piece_at(target_sq)
                if target_piece and target_piece.color == enemy:
                    targets.append(chess.square_name(target_sq))
                    target_pieces.append(target_piece.symbol())
                    target_types.append(target_piece.piece_type)

            if len(targets) < 2:
                continue

            # Defense-awareness: a fork forces a concession only if capturing the
            # forker doesn't resolve all threats. Heuristic:
            #   (a) check fork — must address check, concedes other target
            #   (b) forker is defended — capturing it costs material
            #   (c) forker is worth less than max target — ignoring fork loses more
            # King as forker: can't be captured, always forces concession.
            has_king_target = chess.KING in target_types
            forker_defended = (
                piece.piece_type == chess.KING
                or bool(board.attackers(color, sq))
            )
            forker_val = get_piece_value(piece.piece_type, king=1000)
            max_target_val = max(
                get_piece_value(tt, king=1000) for tt in target_types
            )

            is_real_fork = (
                has_king_target
                or forker_defended
                or forker_val < max_target_val
            )
            if not is_real_fork:
                continue

            has_queen_target = chess.QUEEN in target_types

            forks.append(Fork(
                forking_square=chess.square_name(sq),
                forking_piece=piece.symbol(),
                targets=targets,
                target_pieces=target_pieces,
                color=color_name,
                is_check_fork=has_king_target,
                is_royal_fork=has_king_target and has_queen_target,
            ))
    return forks


def _find_hanging(board: chess.Board) -> list[HangingPiece]:
    """Find hanging pieces using x-ray-aware defense detection from Lichess."""
    from server.lichess_tactics import is_hanging as _lichess_is_hanging

    hanging = []
    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        for sq in chess.SquareSet(board.occupied_co[color]):
            piece = board.piece_at(sq)
            if piece is None or piece.piece_type == chess.KING:
                continue
            attackers = board.attackers(enemy, sq)
            if attackers and _lichess_is_hanging(board, piece, sq):
                if color == board.turn:
                    # Owner moves next — check if piece has any legal move.
                    # board.legal_moves handles pin restrictions: a pinned piece
                    # can only move along the pin line, which is correct.
                    can_retreat = any(m.from_square == sq for m in board.legal_moves)
                else:
                    # Opponent moves next — can capture immediately
                    can_retreat = False
                hanging.append(HangingPiece(
                    square=chess.square_name(sq),
                    piece=piece.symbol(),
                    attacker_squares=[chess.square_name(a) for a in attackers],
                    color=_color_name(color),
                    can_retreat=can_retreat,
                ))
    return hanging


def _find_double_checks(board: chess.Board) -> list[DoubleCheck]:
    """Detect double check (two pieces giving check simultaneously)."""
    if board.is_check() and len(board.checkers()) > 1:
        # The checking side is the side NOT to move (they just moved)
        checking_color = _color_name(not board.turn)
        return [DoubleCheck(
            checker_squares=[chess.square_name(sq) for sq in board.checkers()],
            color=checking_color,
        )]
    return []


def _find_trapped_pieces(board: chess.Board) -> list[TrappedPiece]:
    """Find pieces with no safe escape using Lichess trapped-piece detection."""
    from server.lichess_tactics import is_trapped as _lichess_is_trapped

    trapped = []
    for color in (chess.WHITE, chess.BLACK):
        # is_trapped uses board.legal_moves, which only works for side to move.
        # Use null move to flip turn for the non-moving side.
        needs_null_move = color != board.turn
        if needs_null_move:
            board.push(chess.Move.null())

        # Guard: skip if position is invalid after null move.
        # is_check(): current side in check (their legal_moves would be evasions only).
        # was_into_check(): null move left the OTHER king in check (position is illegal).
        skip = board.is_check() or (needs_null_move and board.was_into_check())
        if not skip:
            for sq in chess.SquareSet(board.occupied_co[color]):
                piece = board.piece_at(sq)
                if piece is None:
                    continue
                if _lichess_is_trapped(board, sq):
                    trapped.append(TrappedPiece(
                        square=chess.square_name(sq),
                        piece=piece.symbol(),
                        color=_color_name(color),
                    ))

        if needs_null_move:
            board.pop()

    return trapped


def _find_mate_patterns(board: chess.Board) -> list[MatePattern]:
    """Detect named checkmate patterns using Lichess pattern detectors."""
    if not board.is_checkmate():
        return []

    from server.lichess_tactics._cook import (
        arabian_mate,
        anastasia_mate,
        back_rank_mate,
        boden_or_double_bishop_mate,
        dovetail_mate,
        hook_mate,
        smothered_mate,
    )

    patterns = []
    if back_rank_mate(board):
        patterns.append(MatePattern(pattern="back_rank"))
    if smothered_mate(board):
        patterns.append(MatePattern(pattern="smothered"))
    if arabian_mate(board):
        patterns.append(MatePattern(pattern="arabian"))
    if hook_mate(board):
        patterns.append(MatePattern(pattern="hook"))
    if anastasia_mate(board):
        patterns.append(MatePattern(pattern="anastasia"))
    if dovetail_mate(board):
        patterns.append(MatePattern(pattern="dovetail"))

    boden_result = boden_or_double_bishop_mate(board)
    if boden_result == "bodenMate":
        patterns.append(MatePattern(pattern="boden"))
    elif boden_result == "doubleBishopMate":
        patterns.append(MatePattern(pattern="double_bishop"))

    return patterns


def _find_mate_threats(board: chess.Board) -> list[MateThreat]:
    """Detect if one side threatens checkmate on the next move."""
    threats = []
    # Check if the side to move can deliver checkmate
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            color_name = _color_name(not board.turn)
            threats.append(MateThreat(
                threatening_color=color_name,
                mating_square=chess.square_name(move.to_square),
            ))
            board.pop()
            break  # One threat is enough
        board.pop()
    return threats


def _find_back_rank_weaknesses(board: chess.Board) -> list[BackRankWeakness]:
    """Detect back rank vulnerability: king on back rank with no escape,
    and opponent has a rook or queen that could threaten it."""
    weaknesses = []
    for color in (chess.WHITE, chess.BLACK):
        king_sq = board.king(color)
        if king_sq is None:
            continue
        back_rank = 0 if color == chess.WHITE else 7
        if chess.square_rank(king_sq) != back_rank:
            continue

        # Check if king has any legal move off the back rank.
        # Use null move to flip turn if this isn't the side to move.
        needs_null_move = color != board.turn
        if needs_null_move:
            board.push(chess.Move.null())

        can_escape = False
        if not board.is_check():
            for move in board.legal_moves:
                if move.from_square == king_sq and chess.square_rank(move.to_square) != back_rank:
                    can_escape = True
                    break

        if needs_null_move:
            board.pop()

        if can_escape:
            continue

        # Opponent has a rook or queen (potential back-rank attacker)
        enemy = not color
        has_heavy = (
            bool(board.pieces(chess.ROOK, enemy))
            or bool(board.pieces(chess.QUEEN, enemy))
        )
        if has_heavy:
            weaknesses.append(BackRankWeakness(
                weak_color=_color_name(color),
                king_square=chess.square_name(king_sq),
            ))
    return weaknesses


def _find_exposed_kings(board: chess.Board) -> list[ExposedKing]:
    """Find exposed kings (advanced past rank 4 with no pawn shield)."""
    from server.lichess_tactics._cook import exposed_king as _lichess_exposed_king

    exposed = []
    for pov in (chess.WHITE, chess.BLACK):
        if _lichess_exposed_king(board, pov):
            opponent = not pov
            king_sq = board.king(opponent)
            if king_sq is not None:
                exposed.append(ExposedKing(
                    color=_color_name(opponent),
                    king_square=chess.square_name(king_sq),
                ))
    return exposed


def _find_overloaded_pieces(board: chess.Board) -> list[OverloadedPiece]:
    """Find pieces that are the sole defender of 2+ attacked targets."""
    overloaded = []
    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        for sq in chess.SquareSet(board.occupied_co[color]):
            piece = board.piece_at(sq)
            if piece is None or piece.piece_type in (chess.PAWN, chess.KING):
                continue
            # Find friendly pieces this piece defends that are attacked by enemy
            sole_defended: list[int] = []
            for defended_sq in board.attacks(sq):
                defended_piece = board.piece_at(defended_sq)
                if defended_piece is None or defended_piece.color != color:
                    continue
                if defended_piece.piece_type == chess.KING:
                    continue
                # Must be attacked by enemy
                if not board.attackers(enemy, defended_sq):
                    continue
                # Check if this is the sole defender (no other same-color defenders)
                all_defenders = board.attackers(color, defended_sq)
                other_defenders = chess.SquareSet(all_defenders) - chess.SquareSet(chess.BB_SQUARES[sq])
                if not other_defenders:
                    sole_defended.append(defended_sq)
            if len(sole_defended) >= 2:
                overloaded.append(OverloadedPiece(
                    square=chess.square_name(sq),
                    piece=piece.symbol(),
                    defended_squares=[chess.square_name(s) for s in sole_defended],
                    color=_color_name(color),
                ))
    return overloaded


def _find_capturable_defenders(board: chess.Board) -> list[CapturableDefender]:
    """Find defenders that can be captured, leaving their charge hanging."""
    results = []
    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        for def_sq in chess.SquareSet(board.occupied_co[color]):
            defender = board.piece_at(def_sq)
            if defender is None or defender.piece_type == chess.KING:
                continue
            # Defender must be capturable by enemy
            enemy_attackers = board.attackers(enemy, def_sq)
            if not enemy_attackers:
                continue
            # Find pieces this defender protects that are attacked
            for charge_sq in board.attacks(def_sq):
                charge = board.piece_at(charge_sq)
                if charge is None or charge.color != color:
                    continue
                if charge.piece_type == chess.KING:
                    continue
                # Charge must be attacked by enemy
                if not board.attackers(enemy, charge_sq):
                    continue
                # Must be sole defender
                all_defenders = board.attackers(color, charge_sq)
                other_defenders = chess.SquareSet(all_defenders) - chess.SquareSet(chess.BB_SQUARES[def_sq])
                if other_defenders:
                    continue
                # The charge must be worth enough to matter
                charge_val = get_piece_value(charge.piece_type, king=0)
                if charge_val < 3:
                    continue
                # Pick the first attacker of the defender
                first_attacker = list(enemy_attackers)[0]
                results.append(CapturableDefender(
                    defender_square=chess.square_name(def_sq),
                    defender_piece=defender.symbol(),
                    charge_square=chess.square_name(charge_sq),
                    charge_piece=charge.symbol(),
                    attacker_square=chess.square_name(first_attacker),
                    color=_color_name(color),
                ))
    return results


def analyze_tactics(board: chess.Board) -> TacticalMotifs:
    ray = _find_ray_motifs(board)
    return TacticalMotifs(
        pins=ray.pins,
        forks=_find_forks(board),
        skewers=ray.skewers,
        hanging=_find_hanging(board),
        discovered_attacks=ray.discovered_attacks,
        double_checks=_find_double_checks(board),
        trapped_pieces=_find_trapped_pieces(board),
        mate_patterns=_find_mate_patterns(board),
        mate_threats=_find_mate_threats(board),
        back_rank_weaknesses=_find_back_rank_weaknesses(board),
        xray_attacks=ray.xray_attacks,
        xray_defenses=ray.xray_defenses,
        exposed_kings=_find_exposed_kings(board),
        overloaded_pieces=_find_overloaded_pieces(board),
        capturable_defenders=_find_capturable_defenders(board),
    )


# ---------------------------------------------------------------------------
# 6. Open Files & Diagonals
# ---------------------------------------------------------------------------


@dataclass
class FileStatus:
    file: int  # 0-7
    is_open: bool
    semi_open_white: bool  # no white pawns
    semi_open_black: bool  # no black pawns


@dataclass
class FilesAndDiagonals:
    files: list[FileStatus]
    rooks_on_open_files: list[str]  # square names
    rooks_on_semi_open_files: list[str]
    bishops_on_long_diagonals: list[str]


def analyze_files_and_diagonals(board: chess.Board) -> FilesAndDiagonals:
    file_statuses = []
    for f in range(8):
        file_bb = chess.BB_FILES[f]
        wp = bool(board.pieces(chess.PAWN, chess.WHITE) & file_bb)
        bp = bool(board.pieces(chess.PAWN, chess.BLACK) & file_bb)
        file_statuses.append(FileStatus(
            file=f,
            is_open=not wp and not bp,
            semi_open_white=not wp and bp,
            semi_open_black=wp and not bp,
        ))

    rooks_open = []
    rooks_semi = []
    for color in (chess.WHITE, chess.BLACK):
        for sq in board.pieces(chess.ROOK, color):
            f = chess.square_file(sq)
            fs = file_statuses[f]
            if fs.is_open:
                rooks_open.append(chess.square_name(sq))
            elif (color == chess.WHITE and fs.semi_open_white) or \
                 (color == chess.BLACK and fs.semi_open_black):
                rooks_semi.append(chess.square_name(sq))

    bishops_long = []
    for color in (chess.WHITE, chess.BLACK):
        for sq in board.pieces(chess.BISHOP, color):
            sq_bb = chess.BB_SQUARES[sq]
            for diag in LONG_DIAGONALS:
                if sq_bb & diag:
                    bishops_long.append(chess.square_name(sq))
                    break

    return FilesAndDiagonals(
        files=file_statuses,
        rooks_on_open_files=rooks_open,
        rooks_on_semi_open_files=rooks_semi,
        bishops_on_long_diagonals=bishops_long,
    )


# ---------------------------------------------------------------------------
# 7. Center Control
# ---------------------------------------------------------------------------


@dataclass
class CenterControl:
    white_pawn_control: int
    white_piece_control: int
    black_pawn_control: int
    black_piece_control: int
    white_total: int
    black_total: int


def analyze_center_control(board: chess.Board) -> CenterControl:
    wp, wpc = 0, 0
    bp, bpc = 0, 0
    for sq in CENTER_SQUARES:
        for attacker_sq in board.attackers(chess.WHITE, sq):
            pt = board.piece_type_at(attacker_sq)
            if pt == chess.PAWN:
                wp += 1
            else:
                wpc += 1
        for attacker_sq in board.attackers(chess.BLACK, sq):
            pt = board.piece_type_at(attacker_sq)
            if pt == chess.PAWN:
                bp += 1
            else:
                bpc += 1
    return CenterControl(
        white_pawn_control=wp,
        white_piece_control=wpc,
        black_pawn_control=bp,
        black_piece_control=bpc,
        white_total=wp + wpc,
        black_total=bp + bpc,
    )


# ---------------------------------------------------------------------------
# 8. Development
# ---------------------------------------------------------------------------


@dataclass
class Development:
    white_developed: int  # 0-4
    black_developed: int  # 0-4
    white_castled: str
    black_castled: str


def analyze_development(board: chess.Board) -> Development:
    def _count_developed(color: chess.Color) -> int:
        """Count surviving minor pieces not on their starting squares."""
        total_minors = (
            len(board.pieces(chess.KNIGHT, color))
            + len(board.pieces(chess.BISHOP, color))
        )
        on_home = sum(
            1 for home_sq, pt in STARTING_MINORS[color]
            if (p := board.piece_at(home_sq)) is not None
            and p.color == color
            and p.piece_type == pt
        )
        return total_minors - on_home

    ks_w = analyze_king_safety(board, chess.WHITE)
    ks_b = analyze_king_safety(board, chess.BLACK)

    return Development(
        white_developed=_count_developed(chess.WHITE),
        black_developed=_count_developed(chess.BLACK),
        white_castled=ks_w.castled,
        black_castled=ks_b.castled,
    )


# ---------------------------------------------------------------------------
# 9. Space
# ---------------------------------------------------------------------------


@dataclass
class Space:
    white_squares: int  # squares controlled in black's half (ranks 5-8)
    black_squares: int  # squares controlled in white's half (ranks 1-4)


def analyze_space(board: chess.Board) -> Space:
    white_controlled: set[int] = set()
    black_controlled: set[int] = set()

    for sq in chess.SQUARES:
        # White targets ranks 4-7 (0-indexed) = ranks 5-8
        if chess.square_rank(sq) >= 4:
            if board.attackers(chess.WHITE, sq):
                white_controlled.add(sq)
        # Black targets ranks 0-3 (0-indexed) = ranks 1-4
        if chess.square_rank(sq) < 4:
            if board.attackers(chess.BLACK, sq):
                black_controlled.add(sq)

    return Space(
        white_squares=len(white_controlled),
        black_squares=len(black_controlled),
    )


# ---------------------------------------------------------------------------
# Top-Level Report
# ---------------------------------------------------------------------------


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


def summarize_position(report: PositionReport) -> str:
    """Produce a concise summary of the most salient position features.

    Selective — only mentions features that are noteworthy.
    All pieces are identified with color and square.
    """
    parts: list[str] = []

    # Check / checkmate status first
    if report.is_checkmate:
        parts.append("Checkmate.")
    elif report.is_check:
        side_in_check = report.turn.capitalize()
        parts.append(f"{side_in_check} is in check.")

    # Material
    mat = report.material
    if mat.imbalance > 0:
        parts.append(f"White is up approximately {mat.imbalance} points of material.")
    elif mat.imbalance < 0:
        parts.append(f"Black is up approximately {-mat.imbalance} points of material.")

    # Tactical motifs — show up to 3 per type, with colored piece identification
    tac = report.tactics
    for fork in tac.forks[:3]:
        if fork.target_pieces:
            target_descs = [
                f"{_colored(tp)} on {sq}"
                for tp, sq in zip(fork.target_pieces, fork.targets)
            ]
        else:
            target_descs = fork.targets
        parts.append(
            f"{_colored(fork.forking_piece)} on {fork.forking_square} "
            f"forks {' and '.join(target_descs)}."
        )
    for pin in tac.pins[:3]:
        abs_label = " (absolutely pinned, cannot move)" if pin.is_absolute else ""
        if pin.pinned_to_piece:
            to_desc = f"{_colored(pin.pinned_to_piece)} on {pin.pinned_to}"
        else:
            to_desc = pin.pinned_to
        parts.append(
            f"{_colored(pin.pinned_piece)} on {pin.pinned_square} is pinned by "
            f"{_colored(pin.pinner_piece)} on {pin.pinner_square} "
            f"to {to_desc}{abs_label}."
        )
    for skewer in tac.skewers[:3]:
        parts.append(
            f"{_colored(skewer.attacker_piece)} on {skewer.attacker_square} skewers "
            f"{_colored(skewer.front_piece)} on {skewer.front_square} behind "
            f"{_colored(skewer.behind_piece)} on {skewer.behind_square}."
        )
    for hp in tac.hanging[:3]:
        color_label = hp.color.capitalize() if hp.color else ""
        piece_desc = f"{color_label} {hp.piece.upper()}" if color_label else _colored(hp.piece)
        if hp.can_retreat:
            parts.append(f"{piece_desc} on {hp.square} is undefended (must move).")
        else:
            captor = "Black" if hp.color == "white" else "White"
            parts.append(f"{piece_desc} on {hp.square} is hanging ({captor} can capture).")
    for da in tac.discovered_attacks[:3]:
        if da.significance == "low":
            continue
        parts.append(
            f"{_colored(da.blocker_piece)} on {da.blocker_square} reveals "
            f"{_colored(da.slider_piece)} on {da.slider_square} targeting "
            f"{_colored(da.target_piece)} on {da.target_square}."
        )
    if tac.double_checks:
        for dc in tac.double_checks[:3]:
            squares = ", ".join(dc.checker_squares)
            parts.append(f"Double check from {squares}.")
    for tp in tac.trapped_pieces[:3]:
        parts.append(f"{_colored(tp.piece)} on {tp.square} is trapped.")
    if tac.mate_patterns:
        pattern_names = {
            "back_rank": "back-rank mate",
            "smothered": "smothered mate",
            "arabian": "Arabian mate",
            "hook": "hook mate",
            "anastasia": "Anastasia's mate",
            "dovetail": "dovetail mate",
            "boden": "Boden's mate",
            "double_bishop": "double bishop mate",
        }
        mp = tac.mate_patterns[0]
        name = pattern_names.get(mp.pattern, f"{mp.pattern} mate")
        parts.append(f"This is a {name}.")
    for mt in tac.mate_threats[:3]:
        parts.append(f"{mt.threatening_color.capitalize()} threatens checkmate on {mt.mating_square}.")
    for bw in tac.back_rank_weaknesses[:3]:
        parts.append(f"{bw.weak_color.capitalize()}'s back rank is weak (king on {bw.king_square}).")
    for xa in tac.xray_attacks[:3]:
        parts.append(
            f"{_colored(xa.slider_piece)} on {xa.slider_square} x-rays through "
            f"{_colored(xa.through_piece)} on {xa.through_square} to "
            f"{_colored(xa.target_piece)} on {xa.target_square}."
        )
    for ek in tac.exposed_kings[:3]:
        parts.append(f"{ek.color.capitalize()}'s king on {ek.king_square} is exposed.")
    for op in tac.overloaded_pieces[:3]:
        charges = ", ".join(op.defended_squares)
        parts.append(
            f"{_colored(op.piece)} on {op.square} is overloaded, sole defender of {charges}."
        )
    for cd in tac.capturable_defenders[:3]:
        parts.append(
            f"{_colored(cd.defender_piece)} on {cd.defender_square} is a capturable defender "
            f"(attacked by {cd.attacker_square}), defends "
            f"{_colored(cd.charge_piece)} on {cd.charge_square}."
        )

    # Pawn weaknesses
    ps = report.pawn_structure
    w_isolated = [p.square for p in ps.white if p.is_isolated]
    b_isolated = [p.square for p in ps.black if p.is_isolated]
    if w_isolated:
        parts.append(f"White has isolated pawns on {', '.join(w_isolated)}.")
    if b_isolated:
        parts.append(f"Black has isolated pawns on {', '.join(b_isolated)}.")

    w_passed = [p.square for p in ps.white if p.is_passed]
    b_passed = [p.square for p in ps.black if p.is_passed]
    if w_passed:
        parts.append(f"White has passed pawns on {', '.join(w_passed)}.")
    if b_passed:
        parts.append(f"Black has passed pawns on {', '.join(b_passed)}.")

    # King safety issues
    for color, ks in [("White", report.king_safety_white), ("Black", report.king_safety_black)]:
        if ks.open_files_near_king:
            parts.append(f"{color}'s king has open files nearby.")

    # Development
    dev = report.development
    if report.fullmove_number <= 15:
        if dev.white_developed < 3:
            parts.append("White has not fully developed minor pieces.")
        if dev.black_developed < 3:
            parts.append("Black has not fully developed minor pieces.")

    # If nothing notable, say so
    if not parts:
        parts.append("The position is roughly balanced with no major imbalances.")

    return " ".join(parts[:8])


def analyze(board: chess.Board) -> PositionReport:
    return PositionReport(
        fen=board.fen(),
        turn=_color_name(board.turn),
        fullmove_number=board.fullmove_number,
        is_check=board.is_check(),
        is_checkmate=board.is_checkmate(),
        is_stalemate=board.is_stalemate(),
        material=analyze_material(board),
        pawn_structure=analyze_pawn_structure(board),
        king_safety_white=analyze_king_safety(board, chess.WHITE),
        king_safety_black=analyze_king_safety(board, chess.BLACK),
        activity=analyze_activity(board),
        tactics=analyze_tactics(board),
        files_and_diagonals=analyze_files_and_diagonals(board),
        center_control=analyze_center_control(board),
        development=analyze_development(board),
        space=analyze_space(board),
    )
