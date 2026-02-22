"""Tests for the LLM orchestrator module."""

import httpx

from server.llm import (
    ChessTeacher,
    OpponentMoveContext,
    _parse_move_selection,
)
from server.prompts import format_coaching_prompt
from server.screener import CoachingContext
from server.annotator import AnnotatedLine, PlyAnnotation
from server.analysis import TacticalMotifs


def _sample_player_line(**overrides) -> AnnotatedLine:
    defaults = dict(
        first_move_san="e4",
        first_move_uci="e2e4",
        score_cp=-30,
        score_mate=None,
        pv_san=["e4", "e5", "Nf3"],
        annotations=[
            PlyAnnotation(
                ply=0,
                fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
                move_san="e4",
                tactics=TacticalMotifs(),
                material_change=0,
                new_motifs=[],
                position_summary="The position is roughly balanced.",
            ),
        ],
    )
    defaults.update(overrides)
    return AnnotatedLine(**defaults)


def _sample_context(**overrides) -> CoachingContext:
    defaults = dict(
        player_move=_sample_player_line(),
        best_lines=[
            AnnotatedLine(
                first_move_san="d4",
                first_move_uci="d2d4",
                score_cp=30,
                score_mate=None,
                pv_san=["d4", "d5", "c4"],
                annotations=[
                    PlyAnnotation(
                        ply=0,
                        fen="rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1",
                        move_san="d4",
                        tactics=TacticalMotifs(),
                        material_change=0,
                        new_motifs=[],
                        position_summary="The position is roughly balanced.",
                    ),
                ],
            ),
        ],
        quality="mistake",
        cp_loss=60,
        player_color="White",
    )
    defaults.update(overrides)
    return CoachingContext(**defaults)


class TestFormatCoachingPrompt:
    def test_contains_player_move(self):
        ctx = _sample_context()
        prompt = format_coaching_prompt(ctx)
        assert "Student played: e4" in prompt

    def test_contains_best_line(self):
        ctx = _sample_context()
        prompt = format_coaching_prompt(ctx)
        assert "d4" in prompt

    def test_contains_quality(self):
        ctx = _sample_context()
        prompt = format_coaching_prompt(ctx)
        assert "mistake" in prompt

    def test_contains_rag_context_when_present(self):
        ctx = _sample_context(rag_context="A fork attacks two pieces simultaneously.")
        prompt = format_coaching_prompt(ctx)
        assert "Relevant chess knowledge" in prompt
        assert "fork attacks two pieces" in prompt

    def test_omits_rag_when_empty(self):
        ctx = _sample_context(rag_context="")
        prompt = format_coaching_prompt(ctx)
        assert "Relevant chess knowledge" not in prompt

    def test_shows_new_motifs(self):
        ann = PlyAnnotation(
            ply=0, fen="...", move_san="Nf7",
            tactics=TacticalMotifs(),
            material_change=0,
            new_motifs=["fork", "hanging_piece"],
            position_summary="Fork on f7.",
        )
        line = AnnotatedLine(
            first_move_san="Nf7", first_move_uci="g5f7",
            score_cp=300, score_mate=None,
            pv_san=["Nf7"], annotations=[ann],
        )
        ctx = _sample_context(best_lines=[line])
        prompt = format_coaching_prompt(ctx)
        assert "fork" in prompt
        assert "hanging_piece" in prompt

    def test_shows_material_change(self):
        ann = PlyAnnotation(
            ply=0, fen="...", move_san="exd5",
            tactics=TacticalMotifs(),
            material_change=100,
            new_motifs=[],
            position_summary="White captured a pawn.",
        )
        line = AnnotatedLine(
            first_move_san="exd5", first_move_uci="e4d5",
            score_cp=100, score_mate=None,
            pv_san=["exd5"], annotations=[ann],
        )
        ctx = _sample_context(best_lines=[line])
        prompt = format_coaching_prompt(ctx)
        assert "material gains 100 cp" in prompt

    def test_omits_empty_ply_annotations(self):
        """Plies with no motifs and no material change are omitted."""
        ann = PlyAnnotation(
            ply=0, fen="...", move_san="Nf3",
            tactics=TacticalMotifs(),
            material_change=0,
            new_motifs=[],
            position_summary="Balanced.",
        )
        line = AnnotatedLine(
            first_move_san="Nf3", first_move_uci="g1f3",
            score_cp=10, score_mate=None,
            pv_san=["Nf3", "Nc6"], annotations=[ann],
        )
        ctx = _sample_context(best_lines=[line])
        prompt = format_coaching_prompt(ctx)
        assert "no new tactical motifs" not in prompt

    def test_filters_player_move_from_alternatives(self):
        """Player's own move should not appear as 'Stronger move'."""
        same_as_player = AnnotatedLine(
            first_move_san="e4", first_move_uci="e2e4",
            score_cp=30, score_mate=None,
            pv_san=["e4", "e5"], annotations=[],
        )
        different = AnnotatedLine(
            first_move_san="d4", first_move_uci="d2d4",
            score_cp=40, score_mate=None,
            pv_san=["d4", "d5"], annotations=[],
        )
        ctx = _sample_context(best_lines=[same_as_player, different])
        prompt = format_coaching_prompt(ctx)
        # "Stronger move" should be d4, not e4
        assert "Stronger alternative: d4" in prompt
        assert "Stronger alternative: e4" not in prompt


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
        result = await teacher.explain_move("You played e4. Stronger move: d4.")
        assert result == "Nice try, but d4 controls the center better."

    async def test_timeout_returns_none(self, monkeypatch):
        """On timeout, explain_move returns None."""
        teacher = ChessTeacher(ollama_url="http://fake", timeout=0.01)

        async def mock_post(self, url, **kwargs):
            raise httpx.ReadTimeout("timed out")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await teacher.explain_move("test prompt")
        assert result is None

    async def test_connection_error_returns_none(self, monkeypatch):
        """On connection failure, explain_move returns None."""
        teacher = ChessTeacher(ollama_url="http://fake", timeout=2.0)

        async def mock_post(self, url, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await teacher.explain_move("test prompt")
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
        result = await teacher.explain_move("test prompt")
        assert result is None


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
