"""Pawn structure analysis: isolated, doubled, passed, backward, chains."""

from dataclasses import dataclass, field

import chess

__all__ = [
    "PawnDetail",
    "PawnStructure",
    "analyze_pawn_structure",
]


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
        is_isolated = not any(0 <= af <= 7 and _own(af) for af in (f - 1, f + 1))

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
        behind_rank = r - direction
        is_chain_member = (
            0 <= behind_rank <= 7
            and any(0 <= af <= 7 and behind_rank in _own(af) for af in (f - 1, f + 1))
        )

        # Chain base: not a chain member, but supports a pawn ahead
        is_chain_base = False
        if not is_chain_member:
            ahead_rank = r + direction
            is_chain_base = (
                0 <= ahead_rank <= 7
                and any(0 <= af <= 7 and ahead_rank in _own(af) for af in (f - 1, f + 1))
            )

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
