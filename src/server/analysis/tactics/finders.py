"""Tactical motif finders: forks, hanging, trapped, mates, overloaded, and more."""

import chess

from server.analysis.constants import _color_name, get_piece_value
from server.analysis.tactics.types import (
    BackRankWeakness,
    CapturableDefender,
    DoubleCheck,
    ExposedKing,
    Fork,
    HangingPiece,
    MatePattern,
    MateThreat,
    OverloadedPiece,
    Pin,
    TrappedPiece,
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
