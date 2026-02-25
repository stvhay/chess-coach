"""Tactical motif detection: pins, forks, skewers, hanging pieces, and more."""

from dataclasses import dataclass, field

import chess

from server.analysis.constants import _color_name, _colored, get_piece_value

__all__ = [
    "Pin",
    "Fork",
    "Skewer",
    "HangingPiece",
    "DiscoveredAttack",
    "DoubleCheck",
    "TrappedPiece",
    "MatePattern",
    "MateThreat",
    "BackRankWeakness",
    "XRayAttack",
    "XRayDefense",
    "ExposedKing",
    "OverloadedPiece",
    "CapturableDefender",
    "TacticalMotifs",
    "PieceInvolvement",
    "index_by_piece",
    "analyze_tactics",
    "_can_defend",
]


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
    is_pin_fork: bool = False     # forker also pins one of the targets


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
    depth: int = 1          # mate-in-N (1 = immediate, 2 = mate-in-2, etc.)
    mating_move: str | None = None  # SAN of the key mating move (if known)


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
class PieceInvolvement:
    motif_type: str   # "pin", "fork", "skewer", "hanging", etc.
    role: str         # "attacker", "target", "defender", "pinned", "blocker"
    motif_index: int  # index into the relevant list in TacticalMotifs


def index_by_piece(tactics: TacticalMotifs) -> dict[str, list[PieceInvolvement]]:
    """Build square -> motif involvement mapping from all detected tactics."""
    idx: dict[str, list[PieceInvolvement]] = {}

    def _add(square: str, motif_type: str, role: str, motif_index: int) -> None:
        idx.setdefault(square, []).append(
            PieceInvolvement(motif_type=motif_type, role=role, motif_index=motif_index)
        )

    for i, pin in enumerate(tactics.pins):
        _add(pin.pinner_square, "pin", "attacker", i)
        _add(pin.pinned_square, "pin", "pinned", i)
        _add(pin.pinned_to, "pin", "target", i)

    for i, fork in enumerate(tactics.forks):
        _add(fork.forking_square, "fork", "attacker", i)
        for t in fork.targets:
            _add(t, "fork", "target", i)

    for i, skewer in enumerate(tactics.skewers):
        _add(skewer.attacker_square, "skewer", "attacker", i)
        _add(skewer.front_square, "skewer", "target", i)
        _add(skewer.behind_square, "skewer", "target", i)

    for i, h in enumerate(tactics.hanging):
        _add(h.square, "hanging", "target", i)
        for a in h.attacker_squares:
            _add(a, "hanging", "attacker", i)

    for i, da in enumerate(tactics.discovered_attacks):
        _add(da.blocker_square, "discovered_attack", "blocker", i)
        _add(da.slider_square, "discovered_attack", "attacker", i)
        _add(da.target_square, "discovered_attack", "target", i)

    for i, dc in enumerate(tactics.double_checks):
        for sq in dc.checker_squares:
            _add(sq, "double_check", "attacker", i)

    for i, tp in enumerate(tactics.trapped_pieces):
        _add(tp.square, "trapped", "target", i)

    # MatePattern has no square fields - skip

    for i, mt in enumerate(tactics.mate_threats):
        _add(mt.mating_square, "mate_threat", "target", i)

    for i, br in enumerate(tactics.back_rank_weaknesses):
        _add(br.king_square, "back_rank_weakness", "target", i)

    for i, xa in enumerate(tactics.xray_attacks):
        _add(xa.slider_square, "xray_attack", "attacker", i)
        _add(xa.through_square, "xray_attack", "target", i)
        _add(xa.target_square, "xray_attack", "target", i)

    for i, xd in enumerate(tactics.xray_defenses):
        _add(xd.slider_square, "xray_defense", "defender", i)
        _add(xd.through_square, "xray_defense", "target", i)
        _add(xd.defended_square, "xray_defense", "defended", i)

    for i, ek in enumerate(tactics.exposed_kings):
        _add(ek.king_square, "exposed_king", "target", i)

    for i, op in enumerate(tactics.overloaded_pieces):
        _add(op.square, "overloaded", "target", i)
        for ds in op.defended_squares:
            _add(ds, "overloaded", "defended", i)

    for i, cd in enumerate(tactics.capturable_defenders):
        _add(cd.defender_square, "capturable_defender", "defender", i)
        _add(cd.charge_square, "capturable_defender", "defended", i)
        _add(cd.attacker_square, "capturable_defender", "attacker", i)

    return idx


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
                        elif first_val > second_val and get_piece_value(pt, king=1000) <= first_val:
                            # Skewer — attacker can win front piece, exposing behind
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


def _find_forks(board: chess.Board, pins: list | None = None) -> list[Fork]:
    # Build pin lookup: (pinner_square, pinned_square) pairs for pin-fork detection
    pin_pairs: set[tuple[str, str]] = set()
    if pins:
        for pin in pins:
            pin_pairs.add((pin.pinner_square, pin.pinned_square))

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
                or piece.piece_type == chess.KING  # king can't be captured
                or forker_val <= max_target_val
            )
            if not is_real_fork:
                continue

            has_queen_target = chess.QUEEN in target_types

            # Pin-fork detection: if the forker also pins one of the targets,
            # this is a compound motif (pin + fork from the same piece)
            forker_sq_name = chess.square_name(sq)
            is_pin_fork = any(
                (forker_sq_name, t) in pin_pairs for t in targets
            )

            forks.append(Fork(
                forking_square=forker_sq_name,
                forking_piece=piece.symbol(),
                targets=targets,
                target_pieces=target_pieces,
                color=color_name,
                is_check_fork=has_king_target,
                is_royal_fork=has_king_target and has_queen_target,
                is_pin_fork=is_pin_fork,
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
        epaulette_mate,
        fools_mate,
        hook_mate,
        lolli_mate,
        scholars_mate,
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

    if scholars_mate(board):
        patterns.append(MatePattern(pattern="scholars"))
    if fools_mate(board):
        patterns.append(MatePattern(pattern="fools"))
    if epaulette_mate(board):
        patterns.append(MatePattern(pattern="epaulette"))
    if lolli_mate(board):
        patterns.append(MatePattern(pattern="lolli"))

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


def _can_defend(board: chess.Board, defender_sq: int, target_sq: int, color: chess.Color) -> bool:
    """Check if a defender can actually recapture on target_sq if needed.

    This catches pin-blindness: board.attacks() counts pinned pieces as
    attackers, but an absolutely-pinned piece cannot recapture on a square
    off the pin ray. We simulate the capture and check legality.
    """
    # If not pinned, the piece can always defend (attacks mask is correct)
    if not board.is_pinned(color, defender_sq):
        return True
    # Piece is pinned — check if target is on the pin ray (can still defend along it)
    pin_mask = board.pin(color, defender_sq)
    return target_sq in pin_mask


def _is_sole_defender(
    board: chess.Board, color: chess.Color, defender_sq: int, target_sq: int,
) -> bool:
    """Return True if defender_sq is the only piece of color defending target_sq."""
    return not (board.attackers(color, target_sq) & ~chess.BB_SQUARES[defender_sq])


def _find_overloaded_pieces(
    board: chess.Board,
    back_rank_weaknesses: list[BackRankWeakness] | None = None,
    mate_threats: list[MateThreat] | None = None,
) -> list[OverloadedPiece]:
    """Find pieces that are the sole defender of 2+ duties.

    Duties include:
    - Sole defender of an attacked friendly piece (traditional)
    - Sole defender of a back-rank square against heavy piece intrusion
    - Sole blocker of a mate-threat mating square
    """
    if back_rank_weaknesses is None:
        back_rank_weaknesses = []
    if mate_threats is None:
        mate_threats = []

    overloaded = []
    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        # Collect back-rank squares that need defense for this color
        br_squares: set[int] = set()
        back_rank = 0 if color == chess.WHITE else 7
        for brw in back_rank_weaknesses:
            if brw.weak_color == _color_name(color):
                # All squares on the back rank attacked by enemy heavy pieces
                for f in range(8):
                    sq_br = chess.square(f, back_rank)
                    if board.attackers(enemy, sq_br):
                        br_squares.add(sq_br)

        # Collect mate-threat mating squares that need blocking for this color
        mt_squares: set[int] = set()
        for mt in mate_threats:
            if mt.threatening_color != _color_name(color):
                # This color is threatened
                mt_sq = chess.parse_square(mt.mating_square)
                mt_squares.add(mt_sq)

        for sq in chess.SquareSet(board.occupied_co[color]):
            piece = board.piece_at(sq)
            if piece is None or piece.piece_type in (chess.PAWN, chess.KING):
                continue

            duties: list[int] = []

            # Traditional: sole defender of attacked friendly pieces
            for defended_sq in board.attacks(sq):
                defended_piece = board.piece_at(defended_sq)
                if defended_piece is None or defended_piece.color != color:
                    continue
                if defended_piece.piece_type == chess.KING:
                    continue
                # Must be attacked by enemy
                if not board.attackers(enemy, defended_sq):
                    continue
                if _is_sole_defender(board, color, sq, defended_sq):
                    # Pin-blindness: a pinned piece can't defend off the pin ray
                    if not _can_defend(board, sq, defended_sq, color):
                        continue
                    duties.append(defended_sq)

            # Back-rank duty: sole defender of a critical back-rank square
            for br_sq in br_squares:
                if br_sq in board.attacks(sq) and _is_sole_defender(board, color, sq, br_sq):
                    if not _can_defend(board, sq, br_sq, color):
                        continue
                    if br_sq not in duties:  # avoid double-counting
                        duties.append(br_sq)

            # Mate-threat blocking duty: sole blocker of a mating square
            for mt_sq in mt_squares:
                if mt_sq in board.attacks(sq) and _is_sole_defender(board, color, sq, mt_sq):
                    if not _can_defend(board, sq, mt_sq, color):
                        continue
                    if mt_sq not in duties:
                        duties.append(mt_sq)

            if len(duties) >= 2:
                overloaded.append(OverloadedPiece(
                    square=chess.square_name(sq),
                    piece=piece.symbol(),
                    defended_squares=[chess.square_name(s) for s in duties],
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
                if not _is_sole_defender(board, color, def_sq, charge_sq):
                    continue
                # Pin-blindness: a pinned piece can't defend off the pin ray
                if not _can_defend(board, def_sq, charge_sq, color):
                    continue
                # The charge must be worth enough to matter
                charge_val = get_piece_value(charge.piece_type, king=0)
                if charge_val < 3:
                    continue
                # Pick the least-valuable attacker of the defender (#24)
                sorted_attackers = sorted(
                    enemy_attackers,
                    key=lambda sq: get_piece_value(board.piece_type_at(sq), king=0),
                )
                best_attacker = sorted_attackers[0]
                # Only report if capturing the defender doesn't lose material (#23)
                attacker_val = get_piece_value(board.piece_type_at(best_attacker), king=0)
                defender_val = get_piece_value(defender.piece_type, king=0)
                if attacker_val > defender_val:
                    continue
                results.append(CapturableDefender(
                    defender_square=chess.square_name(def_sq),
                    defender_piece=defender.symbol(),
                    charge_square=chess.square_name(charge_sq),
                    charge_piece=charge.symbol(),
                    attacker_square=chess.square_name(best_attacker),
                    color=_color_name(color),
                ))
    return results


def analyze_tactics(board: chess.Board) -> TacticalMotifs:
    ray = _find_ray_motifs(board)
    mate_threats = _find_mate_threats(board)
    back_rank_weaknesses = _find_back_rank_weaknesses(board)
    return TacticalMotifs(
        pins=ray.pins,
        forks=_find_forks(board, pins=ray.pins),
        skewers=ray.skewers,
        hanging=_find_hanging(board),
        discovered_attacks=ray.discovered_attacks,
        double_checks=_find_double_checks(board),
        trapped_pieces=_find_trapped_pieces(board),
        mate_patterns=_find_mate_patterns(board),
        mate_threats=mate_threats,
        back_rank_weaknesses=back_rank_weaknesses,
        xray_attacks=ray.xray_attacks,
        xray_defenses=ray.xray_defenses,
        exposed_kings=_find_exposed_kings(board),
        overloaded_pieces=_find_overloaded_pieces(
            board,
            back_rank_weaknesses=back_rank_weaknesses,
            mate_threats=mate_threats,
        ),
        capturable_defenders=_find_capturable_defenders(board),
    )
