"""Tests for EngineProtocol ABC contract."""
import inspect

import pytest

from server.engine import EngineAnalysis, EngineProtocol, Evaluation, LineInfo, MoveInfo


def test_engine_protocol_is_abstract():
    """EngineProtocol cannot be instantiated directly."""
    with pytest.raises(TypeError):
        EngineProtocol()


def test_engine_analysis_implements_protocol():
    """EngineAnalysis is a subclass of EngineProtocol."""
    assert issubclass(EngineAnalysis, EngineProtocol)


def test_protocol_has_required_methods():
    """EngineProtocol defines the four engine methods."""
    methods = {"evaluate", "analyze_lines", "best_moves", "find_mate_threats"}
    protocol_methods = {
        name for name, _ in inspect.getmembers(EngineProtocol, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert methods.issubset(protocol_methods)


def test_protocol_evaluate_signature():
    sig = inspect.signature(EngineProtocol.evaluate)
    params = list(sig.parameters.keys())
    assert params == ["self", "fen", "depth"]


def test_protocol_analyze_lines_signature():
    sig = inspect.signature(EngineProtocol.analyze_lines)
    params = list(sig.parameters.keys())
    assert params == ["self", "fen", "n", "depth"]


def test_protocol_best_moves_signature():
    sig = inspect.signature(EngineProtocol.best_moves)
    params = list(sig.parameters.keys())
    assert params == ["self", "fen", "n", "depth"]


def test_protocol_find_mate_threats_signature():
    sig = inspect.signature(EngineProtocol.find_mate_threats)
    params = list(sig.parameters.keys())
    assert params == ["self", "fen", "max_depth", "eval_depth"]
