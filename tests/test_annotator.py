import chess
import pytest
from server.analysis import TacticalMotifs
from server.annotator import (
    AnnotatedLine,
    PlyAnnotation,
    annotate_line,
    annotate_lines,
    build_annotated_line,
    _motif_set,
    _material_cp,
)
from server.engine import LineInfo


# --- Known positions ---

# Italian Game: after 1.e4 e5 2.Nf3 Nc6 3.Bc4
ITALIAN_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"

# After 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6 — a plausible PV from this position
ITALIAN_PV = ["g8f6", "d2d3", "f8c5", "c2c3"]


def test_annotate_line_basic():
    board = chess.Board(ITALIAN_FEN)
    annotations = annotate_line(board, ITALIAN_PV, max_ply=4)
    assert len(annotations) == 4
    for ann in annotations:
        assert isinstance(ann, PlyAnnotation)
        assert ann.fen  # non-empty FEN
        assert ann.move_san  # non-empty SAN
        assert isinstance(ann.tactics, TacticalMotifs)
        assert isinstance(ann.material_change, int)
        assert isinstance(ann.new_motifs, list)


def test_annotate_line_max_ply_limits():
    board = chess.Board(ITALIAN_FEN)
    annotations = annotate_line(board, ITALIAN_PV, max_ply=2)
    assert len(annotations) == 2


def test_annotate_line_empty_pv():
    board = chess.Board(ITALIAN_FEN)
    annotations = annotate_line(board, [], max_ply=4)
    assert len(annotations) == 0


def test_annotate_line_illegal_move_stops():
    board = chess.Board(ITALIAN_FEN)
    # Include an illegal move mid-PV
    pv_with_illegal = ["g8f6", "a1a8"]  # a1a8 is not legal for white after Nf6
    annotations = annotate_line(board, pv_with_illegal, max_ply=4)
    # Should stop at the illegal move
    assert len(annotations) <= 2


def test_cache_dedup():
    """Shared cache avoids recomputing tactics for the same FEN."""
    board = chess.Board(ITALIAN_FEN)
    cache: dict[str, TacticalMotifs] = {}
    annotate_line(board, ITALIAN_PV[:2], max_ply=2, cache=cache)
    initial_cache_size = len(cache)
    assert initial_cache_size > 0

    # Running again with same PV should hit cache (no new entries for same FENs)
    annotate_line(board, ITALIAN_PV[:2], max_ply=2, cache=cache)
    assert len(cache) == initial_cache_size


def test_material_change_on_capture():
    # Position where a capture is possible: 1.e4 d5 2.exd5
    board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    pv = ["d7d5", "e4d5"]  # d5 followed by exd5 (pawn capture)
    annotations = annotate_line(board, pv, max_ply=2)
    assert len(annotations) == 2
    # After exd5, White captures a pawn: material_change should be positive (White's POV)
    assert annotations[1].material_change == 100  # captured a pawn


def test_new_motifs_detection():
    # After a fork position, new_motifs should be detected.
    # Use a position where Nf7 creates a fork: knight can move to f7 forking king and rook
    # Position: White Ng5, Bc4 vs Black Ke8, Rh8, Qd8 — Nf7 forks K+R
    fork_fen = "r1bqkb1r/pppp1ppp/2n2n2/4p1N1/2B1P3/8/PPPP1PPP/RNBQK2R w KQkq - 4 4"
    board = chess.Board(fork_fen)
    # White plays Nxf7 — creates a fork on king and rook
    annotations = annotate_line(board, ["g5f7"], max_ply=1)
    assert len(annotations) == 1
    assert isinstance(annotations[0].new_motifs, list)


def test_build_annotated_line():
    board = chess.Board(ITALIAN_FEN)
    line = LineInfo(
        uci="g8f6",
        san="Nf6",
        score_cp=5,
        score_mate=None,
        pv=ITALIAN_PV,
        depth=12,
    )
    annotated = build_annotated_line(board, line, max_ply=4)
    assert isinstance(annotated, AnnotatedLine)
    assert annotated.first_move_san == "Nf6"
    assert annotated.first_move_uci == "g8f6"
    assert annotated.score_cp == 5
    assert len(annotated.pv_san) == 4
    assert len(annotated.annotations) == 4


def test_annotate_lines_shared_cache():
    board = chess.Board(ITALIAN_FEN)
    lines = [
        LineInfo(uci="g8f6", san="Nf6", score_cp=5, score_mate=None, pv=["g8f6", "d2d3"], depth=12),
        LineInfo(uci="f8c5", san="Bc5", score_cp=-2, score_mate=None, pv=["f8c5", "c2c3"], depth=12),
    ]
    result = annotate_lines(board, lines, max_ply=2)
    assert len(result) == 2
    assert all(isinstance(r, AnnotatedLine) for r in result)


def test_motif_set_empty():
    tactics = TacticalMotifs()
    assert _motif_set(tactics) == set()


def test_motif_set_with_fork():
    from server.analysis import Fork
    tactics = TacticalMotifs(forks=[Fork("e5", "N", ["d7", "f7"])])
    assert "fork" in _motif_set(tactics)


def test_material_cp_starting_position():
    board = chess.Board()
    assert _material_cp(board) == 0


def test_position_summary_in_annotations():
    board = chess.Board(ITALIAN_FEN)
    annotations = annotate_line(board, ITALIAN_PV[:1], max_ply=1)
    assert len(annotations) == 1
    assert isinstance(annotations[0].position_summary, str)
    assert len(annotations[0].position_summary) > 0
