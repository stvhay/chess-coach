import chess
import pytest
from server.engine import EngineAnalysis, LineInfo

ITALIAN_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
ILLEGAL_FEN = "8/8/8/8/8/8/6k1/r3K3 b - - 0 1"


@pytest.fixture
async def engine():
    e = EngineAnalysis()
    await e.start()
    yield e
    await e.stop()


async def test_analyze_lines_returns_line_info(engine):
    lines = await engine.analyze_lines(ITALIAN_FEN, n=3, depth=10)
    assert len(lines) >= 1
    assert len(lines) <= 3
    for line in lines:
        assert isinstance(line, LineInfo)
        assert isinstance(line.uci, str)
        assert isinstance(line.san, str)
        assert len(line.pv) >= 1
        assert line.depth > 0


async def test_analyze_lines_pv_are_legal(engine):
    lines = await engine.analyze_lines(ITALIAN_FEN, n=3, depth=10)
    board = chess.Board(ITALIAN_FEN)
    for line in lines:
        temp = board.copy()
        for uci in line.pv:
            move = chess.Move.from_uci(uci)
            assert move in temp.legal_moves
            temp.push(move)


async def test_analyze_lines_first_move_matches_pv(engine):
    lines = await engine.analyze_lines(ITALIAN_FEN, n=3, depth=10)
    for line in lines:
        assert line.uci == line.pv[0]


async def test_analyze_lines_san_correct(engine):
    lines = await engine.analyze_lines(ITALIAN_FEN, n=3, depth=10)
    board = chess.Board(ITALIAN_FEN)
    for line in lines:
        expected_san = board.san(chess.Move.from_uci(line.uci))
        assert line.san == expected_san


async def test_analyze_lines_illegal_position(engine):
    with pytest.raises(ValueError, match="Illegal position"):
        await engine.analyze_lines(ILLEGAL_FEN)


async def test_analyze_lines_invalid_fen(engine):
    with pytest.raises(ValueError):
        await engine.analyze_lines("not a valid fen")


async def test_analyze_lines_scores_present(engine):
    lines = await engine.analyze_lines(ITALIAN_FEN, n=3, depth=10)
    for line in lines:
        assert line.score_cp is not None or line.score_mate is not None
