"""Tests for the LLM orchestrator module."""

import httpx

import chess

from server.llm import (
    ChessTeacher,
    OpponentMoveContext,
    _parse_move_selection,
)
from server.game_tree import GameNode, GameTree
from server.report import serialize_report


def _sample_tree(**overrides) -> GameTree:
    """Build a simple GameTree for testing prompt generation."""
    root = GameNode(board=chess.Board(), source="played")

    # Player's move: e4
    player_move = chess.Move.from_uci("e2e4")
    player_node = root.add_child(player_move, "played", score_cp=-30)

    # Add a continuation child for player
    if player_node.board.turn == chess.BLACK:
        cont_move = chess.Move.from_uci("e7e5")
        if cont_move in player_node.board.legal_moves:
            player_node.add_child(cont_move, "engine")

    # Alternative: d4
    alt_move = chess.Move.from_uci("d2d4")
    alt_node = root.add_child(alt_move, "engine", score_cp=30)
    # Add continuation for alternative
    if alt_node.board.turn == chess.BLACK:
        alt_cont = chess.Move.from_uci("d7d5")
        if alt_cont in alt_node.board.legal_moves:
            alt_node.add_child(alt_cont, "engine")

    return GameTree(root=root, decision_point=root, player_color=chess.WHITE)


def _sample_report(**overrides) -> str:
    """Generate a sample coaching report string."""
    tree = _sample_tree()
    defaults = dict(
        quality="mistake",
        cp_loss=60,
    )
    defaults.update(overrides)
    return serialize_report(tree, **defaults)


class TestSerializeReport:
    def test_contains_player_move(self):
        report = _sample_report()
        assert "# Move Played" in report
        lines = report.split("\n")
        assert any(line.strip() == "1. e4" for line in lines)

    def test_contains_best_line(self):
        report = _sample_report()
        assert "d4" in report

    def test_contains_quality(self):
        report = _sample_report()
        assert "mistake" in report

    def test_contains_rag_context_when_present(self):
        tree = _sample_tree()
        report = serialize_report(tree, "mistake", 60,
                                  rag_context="A fork attacks two pieces simultaneously.")
        assert "Relevant chess knowledge" in report
        assert "fork attacks two pieces" in report

    def test_omits_rag_when_empty(self):
        tree = _sample_tree()
        report = serialize_report(tree, "mistake", 60, rag_context="")
        assert "Relevant chess knowledge" not in report

    def test_filters_player_move_from_alternatives(self):
        """Player's own move should not appear as 'Stronger Alternative'."""
        report = _sample_report()
        assert "# Stronger Alternative" in report
        # e4 (player move) should not appear after the alternative header
        lines = report.split("\n")
        in_alt = False
        for line in lines:
            if "# Stronger Alternative" in line:
                in_alt = True
            if in_alt and line.strip() == "1. e4":
                assert False, "Player's move appeared as alternative"


class TestExplainMove:
    async def test_success(self, monkeypatch):
        """Mock a successful OpenAI-compatible response; verify string returned."""
        teacher = ChessTeacher(base_url="http://fake", model="test", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            resp = httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Nice try, but d4 controls the center better."}}]},
                request=httpx.Request("POST", url),
            )
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await teacher.explain_move("You played e4. Stronger move: d4.")
        assert result == "Nice try, but d4 controls the center better."

    async def test_timeout_returns_none(self, monkeypatch):
        """On timeout, explain_move returns None."""
        teacher = ChessTeacher(base_url="http://fake", model="test", timeout=0.01)

        async def mock_post(self, url, **kwargs):
            raise httpx.ReadTimeout("timed out")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await teacher.explain_move("test prompt")
        assert result is None

    async def test_connection_error_returns_none(self, monkeypatch):
        """On connection failure, explain_move returns None."""
        teacher = ChessTeacher(base_url="http://fake", model="test", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await teacher.explain_move("test prompt")
        assert result is None

    async def test_bad_json_returns_none(self, monkeypatch):
        """On malformed JSON response, explain_move returns None."""
        teacher = ChessTeacher(base_url="http://fake", model="test", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"unexpected": "shape"},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await teacher.explain_move("test prompt")
        assert result is None

    async def test_api_key_sent_in_header(self, monkeypatch):
        """When api_key is set, Authorization header is sent."""
        teacher = ChessTeacher(base_url="http://fake", model="test", api_key="sk-test", timeout=2.0)
        captured_headers = {}

        async def mock_post(self, url, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "advice"}}]},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        await teacher.explain_move("test")
        assert captured_headers.get("Authorization") == "Bearer sk-test"

    async def test_no_api_key_no_header(self, monkeypatch):
        """When api_key is None, no Authorization header is sent."""
        teacher = ChessTeacher(base_url="http://fake", model="test", timeout=2.0)
        captured_headers = {}

        async def mock_post(self, url, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "advice"}}]},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        await teacher.explain_move("test")
        assert "Authorization" not in captured_headers


class TestParseMoveSeletion:
    def test_valid_json(self):
        text = '{"selected_move": "Nf3", "reason": "develops with tempo"}'
        result = _parse_move_selection(text)
        assert result == ("Nf3", "develops with tempo")

    def test_json_without_reason(self):
        text = '{"selected_move": "e5"}'
        result = _parse_move_selection(text)
        assert result == ("e5", "")

    def test_messy_llm_output_regex_fallback(self):
        text = 'Sure! Here is my choice:\n{"selected_move": "d5", "reason": "controls center"}\nHope that helps!'
        result = _parse_move_selection(text)
        assert result == ("d5", "controls center")

    def test_garbage_returns_none(self):
        text = "I think Nf3 is a great move because it develops the knight."
        result = _parse_move_selection(text)
        assert result is None

    def test_empty_move_returns_none(self):
        text = '{"selected_move": "", "reason": "no reason"}'
        result = _parse_move_selection(text)
        assert result is None


class TestSelectTeachingMove:
    async def test_success(self, monkeypatch):
        """Mock a successful OpenAI-compatible response with valid JSON."""
        teacher = ChessTeacher(base_url="http://fake", model="test", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"selected_move": "Nf3", "reason": "develops knight"}'}}]},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        ctx = OpponentMoveContext(
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            game_phase="opening",
            position_summary="Roughly balanced opening position.",
            candidates=[
                {"san": "e5", "uci": "e7e5", "score_cp": -10},
                {"san": "Nf6", "uci": "g8f6", "score_cp": -15},
            ],
            player_color="White",
        )
        result = await teacher.select_teaching_move(ctx)
        assert result == ("Nf3", "develops knight")

    async def test_timeout_returns_none(self, monkeypatch):
        """On timeout, select_teaching_move returns None."""
        teacher = ChessTeacher(base_url="http://fake", model="test", timeout=0.01)

        async def mock_post(self, url, **kwargs):
            raise httpx.ReadTimeout("timed out")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        ctx = OpponentMoveContext(
            fen="start", game_phase="opening",
            position_summary="test", candidates=[], player_color="White",
        )
        result = await teacher.select_teaching_move(ctx)
        assert result is None

    async def test_bad_json_returns_none(self, monkeypatch):
        """On garbage LLM output, select_teaching_move returns None."""
        teacher = ChessTeacher(base_url="http://fake", model="test", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "I think e5 is a great move."}}]},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        ctx = OpponentMoveContext(
            fen="start", game_phase="opening",
            position_summary="test", candidates=[], player_color="White",
        )
        result = await teacher.select_teaching_move(ctx)
        assert result is None
