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

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

def _colored(piece_char: str) -> str:
    """Add color prefix: 'N' → 'White N', 'p' → 'Black P'."""
    color = "White" if piece_char.isupper() else "Black"
    return f"{color} {piece_char.upper()}"


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
    return (
        mc.pawns * 1
        + mc.knights * 3
        + mc.bishops * 3
        + mc.rooks * 5
        + mc.queens * 9
    )


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
        white_bishop_pair=wc.bishops >= 2,
        black_bishop_pair=bc.bishops >= 2,
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


def _pawn_files(board: chess.Board, color: chess.Color) -> set[int]:
    """Return set of file indices (0-7) that have pawns of the given color."""
    return {chess.square_file(sq) for sq in board.pieces(chess.PAWN, color)}


def _count_islands(files: set[int]) -> int:
    if not files:
        return 0
    sorted_files = sorted(files)
    islands = 1
    for i in range(1, len(sorted_files)):
        if sorted_files[i] > sorted_files[i - 1] + 1:
            islands += 1
    return islands


def _is_isolated(board: chess.Board, sq: int, color: chess.Color) -> bool:
    f = chess.square_file(sq)
    adj_files = [af for af in (f - 1, f + 1) if 0 <= af <= 7]
    for af in adj_files:
        file_bb = chess.BB_FILES[af]
        if board.pieces(chess.PAWN, color) & file_bb:
            return False
    return True


def _is_doubled(board: chess.Board, sq: int, color: chess.Color) -> bool:
    f = chess.square_file(sq)
    file_bb = chess.BB_FILES[f]
    pawns_on_file = board.pieces(chess.PAWN, color) & file_bb
    return len(pawns_on_file) > 1


def _is_passed(board: chess.Board, sq: int, color: chess.Color) -> bool:
    f = chess.square_file(sq)
    r = chess.square_rank(sq)
    enemy = not color
    check_files = [af for af in (f - 1, f, f + 1) if 0 <= af <= 7]

    for af in check_files:
        file_bb = chess.BB_FILES[af]
        enemy_pawns = board.pieces(chess.PAWN, enemy) & file_bb
        for ep in enemy_pawns:
            er = chess.square_rank(ep)
            if color == chess.WHITE and er > r:
                return False
            if color == chess.BLACK and er < r:
                return False
    return True


def _is_backward(board: chess.Board, sq: int, color: chess.Color) -> bool:
    f = chess.square_file(sq)
    r = chess.square_rank(sq)
    enemy = not color

    # Stop square: one rank ahead
    if color == chess.WHITE:
        if r >= 7:
            return False
        stop_sq = chess.square(f, r + 1)
    else:
        if r <= 0:
            return False
        stop_sq = chess.square(f, r - 1)

    # Stop square must be attacked by enemy pawns
    enemy_pawn_attackers = board.attackers(enemy, stop_sq) & board.pieces(chess.PAWN, enemy)
    if not enemy_pawn_attackers:
        return False

    # No friendly pawn on adjacent files behind or equal rank that could support
    adj_files = [af for af in (f - 1, f + 1) if 0 <= af <= 7]
    for af in adj_files:
        file_bb = chess.BB_FILES[af]
        friendly_pawns = board.pieces(chess.PAWN, color) & file_bb
        for fp in friendly_pawns:
            fr = chess.square_rank(fp)
            if color == chess.WHITE and fr <= r:
                return False
            if color == chess.BLACK and fr >= r:
                return False
    return True


def _is_chain_member(board: chess.Board, sq: int, color: chess.Color) -> bool:
    """A pawn is a chain member if a friendly pawn is diagonally behind it."""
    f = chess.square_file(sq)
    r = chess.square_rank(sq)

    if color == chess.WHITE:
        behind_rank = r - 1
    else:
        behind_rank = r + 1

    if behind_rank < 0 or behind_rank > 7:
        return False

    for af in (f - 1, f + 1):
        if 0 <= af <= 7:
            behind_sq = chess.square(af, behind_rank)
            piece = board.piece_at(behind_sq)
            if piece and piece.piece_type == chess.PAWN and piece.color == color:
                return True
    return False


def _analyze_pawns_for_color(board: chess.Board, color: chess.Color) -> list[PawnDetail]:
    details = []
    for sq in board.pieces(chess.PAWN, color):
        isolated = _is_isolated(board, sq, color)
        doubled = _is_doubled(board, sq, color)
        passed = _is_passed(board, sq, color)
        backward = _is_backward(board, sq, color)
        chain_mem = _is_chain_member(board, sq, color)
        # Chain base: is a chain member but no friendly pawn diagonally behind
        # supporting it — i.e., it supports others but is not itself supported.
        # Actually: chain base = chain member that is NOT supported from behind.
        # We define "chain base" as a pawn that has a friendly pawn diagonally
        # ahead but NOT one diagonally behind.
        chain_base = False
        if not chain_mem:
            # Check if this pawn supports another pawn ahead (making it a base)
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            ahead_rank = r + 1 if color == chess.WHITE else r - 1
            if 0 <= ahead_rank <= 7:
                for af in (f - 1, f + 1):
                    if 0 <= af <= 7:
                        ahead_sq = chess.square(af, ahead_rank)
                        piece = board.piece_at(ahead_sq)
                        if piece and piece.piece_type == chess.PAWN and piece.color == color:
                            chain_base = True
                            break

        details.append(PawnDetail(
            square=chess.square_name(sq),
            is_isolated=isolated,
            is_doubled=doubled,
            is_passed=passed,
            is_backward=backward,
            is_chain_base=chain_base,
            is_chain_member=chain_mem,
        ))
    return details


def analyze_pawn_structure(board: chess.Board) -> PawnStructure:
    w_files = _pawn_files(board, chess.WHITE)
    b_files = _pawn_files(board, chess.BLACK)
    return PawnStructure(
        white=_analyze_pawns_for_color(board, chess.WHITE),
        black=_analyze_pawns_for_color(board, chess.BLACK),
        white_islands=_count_islands(w_files),
        black_islands=_count_islands(b_files),
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

    king_file = chess.square_file(king_sq)
    king_rank = chess.square_rank(king_sq)

    # Castled heuristic
    if color == chess.WHITE:
        castled = "none"
        if king_sq in (chess.G1, chess.H1):
            castled = "kingside"
        elif king_sq in (chess.C1, chess.B1):
            castled = "queenside"
    else:
        castled = "none"
        if king_sq in (chess.G8, chess.H8):
            castled = "kingside"
        elif king_sq in (chess.C8, chess.B8):
            castled = "queenside"

    # Pawn shield: friendly pawns 1-2 ranks ahead on king file +/- 1
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

    # Open / semi-open files near king
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

    return KingSafety(
        king_square=chess.square_name(king_sq),
        castled=castled,
        has_kingside_castling_rights=board.has_kingside_castling_rights(color),
        has_queenside_castling_rights=board.has_queenside_castling_rights(color),
        pawn_shield_count=len(shield_squares),
        pawn_shield_squares=shield_squares,
        open_files_near_king=open_files,
        semi_open_files_near_king=semi_open,
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


@dataclass
class Fork:
    forking_square: str
    forking_piece: str
    targets: list[str]  # squares being forked
    target_pieces: list[str] = field(default_factory=list)  # piece chars on target squares


@dataclass
class Skewer:
    attacker_square: str
    attacker_piece: str
    front_square: str
    front_piece: str
    behind_square: str
    behind_piece: str


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


@dataclass
class DoubleCheck:
    checker_squares: list[str]


@dataclass
class TrappedPiece:
    square: str
    piece: str


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


@dataclass
class ExposedKing:
    color: str  # "white" or "black" — whose king is exposed
    king_square: str


@dataclass
class OverloadedPiece:
    square: str
    piece: str
    defended_squares: list[str]  # attacked targets this piece sole-defends


@dataclass
class CapturableDefender:
    defender_square: str
    defender_piece: str
    charge_square: str   # piece being defended
    charge_piece: str
    attacker_square: str  # who can capture the defender


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
    exposed_kings: list[ExposedKing] = field(default_factory=list)
    overloaded_pieces: list[OverloadedPiece] = field(default_factory=list)
    capturable_defenders: list[CapturableDefender] = field(default_factory=list)


def _find_pins(board: chess.Board) -> list[Pin]:
    pins = []
    for color in (chess.WHITE, chess.BLACK):
        king_sq = board.king(color)
        if king_sq is None:
            continue
        for sq in chess.SquareSet(board.occupied_co[color]):
            if sq == king_sq:
                continue
            if board.is_pinned(color, sq):
                pin_mask = board.pin(color, sq)
                # Find the pinner: enemy piece on the pin ray
                enemy = not color
                for esq in chess.SquareSet(board.occupied_co[enemy]):
                    if esq in pin_mask:
                        ep = board.piece_at(esq)
                        pp = board.piece_at(sq)
                        if ep and pp and ep.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
                            shielded = board.piece_at(king_sq)
                            pins.append(Pin(
                                pinned_square=chess.square_name(sq),
                                pinned_piece=pp.symbol(),
                                pinner_square=chess.square_name(esq),
                                pinner_piece=ep.symbol(),
                                pinned_to=chess.square_name(king_sq),
                                pinned_to_piece=shielded.symbol() if shielded else "",
                                is_absolute=(king_sq == board.king(color)),
                            ))
    return pins


def _find_forks(board: chess.Board) -> list[Fork]:
    forks = []
    for color in (chess.WHITE, chess.BLACK):
        for sq in chess.SquareSet(board.occupied_co[color]):
            piece = board.piece_at(sq)
            if piece is None:
                continue
            piece_val = PIECE_VALUES.get(piece.piece_type, 0)
            attacks = board.attacks(sq)
            enemy = not color
            targets = []
            target_pieces = []
            for target_sq in attacks:
                target_piece = board.piece_at(target_sq)
                if target_piece and target_piece.color == enemy:
                    target_val = PIECE_VALUES.get(target_piece.piece_type, 0)
                    if target_val >= piece_val or target_piece.piece_type == chess.KING:
                        targets.append(chess.square_name(target_sq))
                        target_pieces.append(target_piece.symbol())
            if len(targets) >= 2:
                forks.append(Fork(
                    forking_square=chess.square_name(sq),
                    forking_piece=piece.symbol(),
                    targets=targets,
                    target_pieces=target_pieces,
                ))
    return forks


def _find_skewers(board: chess.Board) -> list[Skewer]:
    skewers = []
    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        for pt in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            for sq in board.pieces(pt, color):
                piece = board.piece_at(sq)
                attacks = board.attacks(sq)
                for target_sq in attacks:
                    target_piece = board.piece_at(target_sq)
                    if target_piece is None or target_piece.color != enemy:
                        continue
                    # Check if there's an occupied square between attacker and target
                    between_mask = chess.between(sq, target_sq) & board.occupied
                    if between_mask:
                        continue  # blocked, not a direct attack
                    # Extend ray past target
                    ray_mask = chess.ray(sq, target_sq)
                    if not ray_mask:
                        continue
                    # Squares past target on the ray
                    beyond = ray_mask & ~chess.BB_SQUARES[sq] & ~chess.BB_SQUARES[target_sq]
                    # Remove squares between sq and target_sq
                    beyond = beyond & ~chess.between(sq, target_sq)
                    # Find the first enemy piece in the beyond direction
                    # We need to iterate in order from target_sq outward
                    file_diff = chess.square_file(target_sq) - chess.square_file(sq)
                    rank_diff = chess.square_rank(target_sq) - chess.square_rank(sq)
                    df = (1 if file_diff > 0 else -1) if file_diff != 0 else 0
                    dr = (1 if rank_diff > 0 else -1) if rank_diff != 0 else 0

                    cur_f = chess.square_file(target_sq) + df
                    cur_r = chess.square_rank(target_sq) + dr
                    found_behind = None
                    while 0 <= cur_f <= 7 and 0 <= cur_r <= 7:
                        csq = chess.square(cur_f, cur_r)
                        occ = board.piece_at(csq)
                        if occ is not None:
                            if occ.color == enemy:
                                found_behind = (csq, occ)
                            break  # blocked
                        cur_f += df
                        cur_r += dr

                    if found_behind:
                        behind_sq, behind_piece = found_behind
                        # Skewer: front piece is more valuable (or king),
                        # so it must move, exposing the piece behind
                        front_val = PIECE_VALUES.get(target_piece.piece_type, 0)
                        behind_val = PIECE_VALUES.get(behind_piece.piece_type, 0)
                        if front_val < behind_val and target_piece.piece_type != chess.KING:
                            continue
                        skewers.append(Skewer(
                            attacker_square=chess.square_name(sq),
                            attacker_piece=piece.symbol(),
                            front_square=chess.square_name(target_sq),
                            front_piece=target_piece.symbol(),
                            behind_square=chess.square_name(behind_sq),
                            behind_piece=behind_piece.symbol(),
                        ))
    return skewers


def _find_hanging(board: chess.Board) -> list[HangingPiece]:
    """Find hanging pieces using x-ray-aware defense detection from Lichess."""
    from server.lichess_tactics import is_hanging as _lichess_is_hanging, is_trapped as _lichess_is_trapped

    hanging = []
    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        for sq in chess.SquareSet(board.occupied_co[color]):
            piece = board.piece_at(sq)
            if piece is None or piece.piece_type == chess.KING:
                continue
            attackers = board.attackers(enemy, sq)
            if attackers and _lichess_is_hanging(board, piece, sq):
                # Can the piece be saved?
                if color == board.turn:
                    # Owner moves next — check if they have escape squares
                    if board.is_pinned(color, sq):
                        can_retreat = False
                    elif piece.piece_type == chess.PAWN:
                        can_retreat = any(m.from_square == sq for m in board.legal_moves)
                    else:
                        can_retreat = not _lichess_is_trapped(board, sq)
                else:
                    # Opponent moves next — can capture immediately
                    can_retreat = False
                hanging.append(HangingPiece(
                    square=chess.square_name(sq),
                    piece=piece.symbol(),
                    attacker_squares=[chess.square_name(a) for a in attackers],
                    color="white" if color == chess.WHITE else "black",
                    can_retreat=can_retreat,
                ))
    return hanging


def _find_discovered_attacks(board: chess.Board) -> list[DiscoveredAttack]:
    discovered = []
    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        # For each friendly slider, check if a single friendly piece blocks its ray to an enemy
        for pt in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            for slider_sq in board.pieces(pt, color):
                # Check rays to enemy pieces
                for target_sq in chess.SquareSet(board.occupied_co[enemy]):
                    target_piece = board.piece_at(target_sq)
                    if target_piece is None:
                        continue
                    ray = chess.ray(slider_sq, target_sq)
                    if not ray:
                        continue
                    # Verify the slider can actually attack along this ray
                    # (bishops on diagonals, rooks on ranks/files)
                    if pt == chess.BISHOP:
                        if chess.square_file(slider_sq) == chess.square_file(target_sq):
                            continue
                        if chess.square_rank(slider_sq) == chess.square_rank(target_sq):
                            continue
                    elif pt == chess.ROOK:
                        if chess.square_file(slider_sq) != chess.square_file(target_sq) and \
                           chess.square_rank(slider_sq) != chess.square_rank(target_sq):
                            continue

                    between_mask = chess.between(slider_sq, target_sq)
                    blockers = chess.SquareSet(between_mask & board.occupied)
                    if len(blockers) == 1:
                        blocker_sq = list(blockers)[0]
                        blocker_piece = board.piece_at(blocker_sq)
                        if blocker_piece and blocker_piece.color == color:
                            # Significance: pawn blocking a rook on a distant
                            # file is nearly always pedagogically worthless
                            sig = "normal"
                            if (blocker_piece.piece_type == chess.PAWN
                                    and pt == chess.ROOK
                                    and PIECE_VALUES.get(target_piece.piece_type, 0) <= 1):
                                sig = "low"
                            discovered.append(DiscoveredAttack(
                                blocker_square=chess.square_name(blocker_sq),
                                blocker_piece=blocker_piece.symbol(),
                                slider_square=chess.square_name(slider_sq),
                                slider_piece=board.piece_at(slider_sq).symbol(),
                                target_square=chess.square_name(target_sq),
                                target_piece=target_piece.symbol(),
                                significance=sig,
                            ))
    return discovered


def _find_double_checks(board: chess.Board) -> list[DoubleCheck]:
    """Detect double check (two pieces giving check simultaneously)."""
    if board.is_check() and len(board.checkers()) > 1:
        return [DoubleCheck(
            checker_squares=[chess.square_name(sq) for sq in board.checkers()]
        )]
    return []


def _find_trapped_pieces(board: chess.Board) -> list[TrappedPiece]:
    """Find pieces with no safe escape using Lichess trapped-piece detection."""
    from server.lichess_tactics import is_trapped as _lichess_is_trapped

    trapped = []
    # Only check pieces of the side to move (is_trapped iterates legal_moves)
    for sq in chess.SquareSet(board.occupied_co[board.turn]):
        piece = board.piece_at(sq)
        if piece is None:
            continue
        if _lichess_is_trapped(board, sq):
            trapped.append(TrappedPiece(
                square=chess.square_name(sq),
                piece=piece.symbol(),
            ))
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
    elif smothered_mate(board):
        patterns.append(MatePattern(pattern="smothered"))
    elif arabian_mate(board):
        patterns.append(MatePattern(pattern="arabian"))
    elif hook_mate(board):
        patterns.append(MatePattern(pattern="hook"))
    elif anastasia_mate(board):
        patterns.append(MatePattern(pattern="anastasia"))
    elif dovetail_mate(board):
        patterns.append(MatePattern(pattern="dovetail"))
    else:
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
            color_name = "white" if board.turn == chess.BLACK else "black"
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

        # Check if escape squares (one rank forward) are all blocked by own pieces
        forward_rank = 1 if color == chess.WHITE else 6
        king_file = chess.square_file(king_sq)
        all_blocked = True
        for f in range(max(0, king_file - 1), min(8, king_file + 2)):
            sq = chess.square(f, forward_rank)
            piece = board.piece_at(sq)
            if piece is None or piece.color != color:
                all_blocked = False
                break

        if not all_blocked:
            continue

        # Opponent has a rook or queen (potential back-rank attacker)
        enemy = not color
        has_heavy = (
            bool(board.pieces(chess.ROOK, enemy))
            or bool(board.pieces(chess.QUEEN, enemy))
        )
        if has_heavy:
            weaknesses.append(BackRankWeakness(
                weak_color="white" if color == chess.WHITE else "black",
                king_square=chess.square_name(king_sq),
            ))
    return weaknesses


def _find_xray_attacks(board: chess.Board) -> list[XRayAttack]:
    """Find x-ray attacks: slider attacks through an enemy piece to a target behind."""
    xrays = []
    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        for pt in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            for slider_sq in board.pieces(pt, color):
                slider_piece = board.piece_at(slider_sq)
                if slider_piece is None:
                    continue
                # Check rays to enemy pieces that have another enemy piece behind
                for through_sq in chess.SquareSet(board.occupied_co[enemy]):
                    through_piece = board.piece_at(through_sq)
                    if through_piece is None:
                        continue
                    ray = chess.ray(slider_sq, through_sq)
                    if not ray:
                        continue
                    # Verify slider type matches the ray direction
                    if pt == chess.BISHOP:
                        if chess.square_file(slider_sq) == chess.square_file(through_sq):
                            continue
                        if chess.square_rank(slider_sq) == chess.square_rank(through_sq):
                            continue
                    elif pt == chess.ROOK:
                        if chess.square_file(slider_sq) != chess.square_file(through_sq) and \
                           chess.square_rank(slider_sq) != chess.square_rank(through_sq):
                            continue
                    # Must be a direct attack on through_sq (no pieces between)
                    between = chess.between(slider_sq, through_sq)
                    if chess.SquareSet(between & board.occupied):
                        continue
                    # Look for an enemy target behind through_sq on the same ray
                    file_diff = chess.square_file(through_sq) - chess.square_file(slider_sq)
                    rank_diff = chess.square_rank(through_sq) - chess.square_rank(slider_sq)
                    df = (1 if file_diff > 0 else -1) if file_diff != 0 else 0
                    dr = (1 if rank_diff > 0 else -1) if rank_diff != 0 else 0
                    cur_f = chess.square_file(through_sq) + df
                    cur_r = chess.square_rank(through_sq) + dr
                    while 0 <= cur_f <= 7 and 0 <= cur_r <= 7:
                        csq = chess.square(cur_f, cur_r)
                        occ = board.piece_at(csq)
                        if occ is not None:
                            if occ.color == enemy:
                                target_val = PIECE_VALUES.get(occ.piece_type, 0)
                                through_val = PIECE_VALUES.get(through_piece.piece_type, 0)
                                # Only interesting if target is valuable (>= through piece or king)
                                if target_val >= through_val or occ.piece_type == chess.KING:
                                    xrays.append(XRayAttack(
                                        slider_square=chess.square_name(slider_sq),
                                        slider_piece=slider_piece.symbol(),
                                        through_square=chess.square_name(through_sq),
                                        through_piece=through_piece.symbol(),
                                        target_square=chess.square_name(csq),
                                        target_piece=occ.symbol(),
                                    ))
                            break  # blocked by any piece
                        cur_f += df
                        cur_r += dr
    return xrays


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
                    color="white" if opponent == chess.WHITE else "black",
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
                ))
    return overloaded


def _find_capturable_defenders(board: chess.Board) -> list[CapturableDefender]:
    """Find defenders that can be captured, leaving their charge hanging."""
    from server.lichess_tactics import is_hanging as _lichess_is_hanging

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
                charge_val = PIECE_VALUES.get(charge.piece_type, 0)
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
                ))
    return results


def analyze_tactics(board: chess.Board) -> TacticalMotifs:
    return TacticalMotifs(
        pins=_find_pins(board),
        forks=_find_forks(board),
        skewers=_find_skewers(board),
        hanging=_find_hanging(board),
        discovered_attacks=_find_discovered_attacks(board),
        double_checks=_find_double_checks(board),
        trapped_pieces=_find_trapped_pieces(board),
        mate_patterns=_find_mate_patterns(board),
        mate_threats=_find_mate_threats(board),
        back_rank_weaknesses=_find_back_rank_weaknesses(board),
        xray_attacks=_find_xray_attacks(board),
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
    w_dev = 0
    for sq, pt in STARTING_MINORS[chess.WHITE]:
        piece = board.piece_at(sq)
        if piece is None or piece.color != chess.WHITE or piece.piece_type != pt:
            w_dev += 1

    b_dev = 0
    for sq, pt in STARTING_MINORS[chess.BLACK]:
        piece = board.piece_at(sq)
        if piece is None or piece.color != chess.BLACK or piece.piece_type != pt:
            b_dev += 1

    ks_w = analyze_king_safety(board, chess.WHITE)
    ks_b = analyze_king_safety(board, chess.BLACK)

    return Development(
        white_developed=w_dev,
        black_developed=b_dev,
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
        turn="white" if board.turn == chess.WHITE else "black",
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
