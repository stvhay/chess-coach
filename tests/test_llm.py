"""Tests for the LLM orchestrator module."""

import httpx

from server.llm import (
    ChessTeacher,
    MoveContext,
    OpponentMoveContext,
    _build_user_prompt,
    _parse_move_selection,
)


def _sample_context(**overrides) -> MoveContext:
    defaults = dict(
        fen_before="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        player_move_san="e4",
        best_move_san="d4",
        quality="mistake",
        cp_loss=130,
        tactics_summary="The knight on f3 is hanging.",
        player_color="White",
    )
    defaults.update(overrides)
    return MoveContext(**defaults)


class TestBuildPrompt:
    def test_contains_player_move(self):
        ctx = _sample_context()
        prompt = _build_user_prompt(ctx)
        assert "e4" in prompt

    def test_contains_best_move(self):
        ctx = _sample_context()
        prompt = _build_user_prompt(ctx)
        assert "d4" in prompt

    def test_contains_quality(self):
        ctx = _sample_context()
        prompt = _build_user_prompt(ctx)
        assert "mistake" in prompt

    def test_contains_tactics_when_present(self):
        ctx = _sample_context(tactics_summary="There is a fork on c7.")
        prompt = _build_user_prompt(ctx)
        assert "fork on c7" in prompt

    def test_omits_tactics_line_when_empty(self):
        ctx = _sample_context(tactics_summary="")
        prompt = _build_user_prompt(ctx)
        assert "Tactical details" not in prompt


class TestExplainMove:
    async def test_success(self, monkeypatch):
        """Mock a successful Ollama response; verify string returned."""
        teacher = ChessTeacher(ollama_url="http://fake", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            resp = httpx.Response(
                200,
                json={"message": {"content": "Nice try, but d4 controls the center better."}},
                request=httpx.Request("POST", url),
            )
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await teacher.explain_move(_sample_context())
        assert result == "Nice try, but d4 controls the center better."

    async def test_timeout_returns_none(self, monkeypatch):
        """On timeout, explain_move returns None."""
        teacher = ChessTeacher(ollama_url="http://fake", timeout=0.01)

        async def mock_post(self, url, **kwargs):
            raise httpx.ReadTimeout("timed out")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await teacher.explain_move(_sample_context())
        assert result is None

    async def test_connection_error_returns_none(self, monkeypatch):
        """On connection failure, explain_move returns None."""
        teacher = ChessTeacher(ollama_url="http://fake", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await teacher.explain_move(_sample_context())
        assert result is None

    async def test_bad_json_returns_none(self, monkeypatch):
        """On malformed JSON response, explain_move returns None."""
        teacher = ChessTeacher(ollama_url="http://fake", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"unexpected": "shape"},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await teacher.explain_move(_sample_context())
        assert result is None


class TestBuildPromptRagContext:
    def test_prompt_includes_rag_context(self):
        ctx = _sample_context(rag_context="A fork attacks two pieces simultaneously.")
        prompt = _build_user_prompt(ctx)
        assert "Relevant chess knowledge" in prompt
        assert "fork attacks two pieces" in prompt

    def test_prompt_omits_rag_when_empty(self):
        ctx = _sample_context(rag_context="")
        prompt = _build_user_prompt(ctx)
        assert "Relevant chess knowledge" not in prompt


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
        """Mock a successful Ollama response with valid JSON."""
        teacher = ChessTeacher(ollama_url="http://fake", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"message": {"content": '{"selected_move": "Nf3", "reason": "develops knight"}'}},
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
        teacher = ChessTeacher(ollama_url="http://fake", timeout=0.01)

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
        teacher = ChessTeacher(ollama_url="http://fake", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"message": {"content": "I think e5 is a great move."}},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        ctx = OpponentMoveContext(
            fen="start", game_phase="opening",
            position_summary="test", candidates=[], player_color="White",
        )
        result = await teacher.select_teaching_move(ctx)
        assert result is None
