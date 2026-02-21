import chess
import pytest
from server.engine import EngineAnalysis, Evaluation


@pytest.fixture
async def engine():
    e = EngineAnalysis()
    await e.start()
    yield e
    await e.stop()


async def test_evaluate_starting_position(engine):
    result = await engine.evaluate("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert isinstance(result, Evaluation)
    assert isinstance(result.score_cp, int | None)
    assert isinstance(result.score_mate, int | None)
    assert result.depth > 0
    assert result.best_move is not None
    # Starting position should be roughly equal
    if result.score_cp is not None:
        assert -100 < result.score_cp < 100


async def test_evaluate_checkmate(engine):
    # A position where White has a huge advantage
    result = await engine.evaluate("rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2")
    assert result.best_move is not None


async def test_best_moves(engine):
    # Italian Game position — multiple reasonable moves
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
    moves = await engine.best_moves(fen, n=3)
    assert len(moves) >= 1
    assert len(moves) <= 3
    for move in moves:
        board = chess.Board(fen)
        parsed = chess.Move.from_uci(move.uci)
        assert parsed in board.legal_moves


async def test_evaluate_invalid_fen(engine):
    with pytest.raises(ValueError):
        await engine.evaluate("not a valid fen")
