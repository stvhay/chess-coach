"""Ray-based tactical detection: pins, skewers, x-rays, discovered attacks."""

import chess

from server.analysis.constants import _color_name, get_piece_value
from server.analysis.tactics.types import (
    DiscoveredAttack,
    Pin,
    Skewer,
    XRayAttack,
    XRayDefense,
    _RAY_DIRS,
    _RayMotifs,
)


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
