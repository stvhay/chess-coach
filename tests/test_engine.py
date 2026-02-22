import chess
import chess.engine
import pytest
from server.engine import EngineAnalysis, Evaluation

# Illegal FEN: black to move, white king in check from a1 rook (opposite check)
ILLEGAL_FEN = "8/8/8/8/8/8/6k1/r3K3 b - - 0 1"


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


async def test_evaluate_illegal_position(engine):
    with pytest.raises(ValueError, match="Illegal position"):
        await engine.evaluate(ILLEGAL_FEN)


async def test_best_moves_illegal_position(engine):
    with pytest.raises(ValueError, match="Illegal position"):
        await engine.best_moves(ILLEGAL_FEN)


async def test_engine_restart_on_crash(engine):
    """Engine transparently recovers after a single EngineTerminatedError."""
    original_analyse = engine._engine.analyse
    call_count = 0

    async def crash_once(board, limit, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise chess.engine.EngineTerminatedError()
        return await original_analyse(board, limit, **kwargs)

    engine._engine.analyse = crash_once
    result = await engine.evaluate(
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", depth=5
    )
    assert result.best_move is not None


async def test_engine_double_crash_raises(engine):
    """Two consecutive crashes raise RuntimeError."""
    async def always_crash(board, limit, **kwargs):
        raise chess.engine.EngineTerminatedError()

    engine._engine.analyse = always_crash
    # After restart, start() gives a fresh engine, but we need that to also crash.
    # Patch start() to install the crashing mock on the new engine too.
    original_start = engine.start

    async def start_with_crash():
        await original_start()
        engine._engine.analyse = always_crash

    engine.start = start_with_crash
    with pytest.raises(RuntimeError, match="Engine restart failed"):
        await engine.evaluate(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", depth=5
        )
