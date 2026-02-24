"""Tests for the knowledge base query construction module."""

import json
import tempfile
from unittest.mock import AsyncMock

from server.analysis import (
    PositionReport,
    MaterialInfo,
    MaterialCount,
    PawnStructure,
    PawnDetail,
    KingSafety,
    ActivityInfo,
    TacticalMotifs,
    Fork,
    Pin,
    HangingPiece,
    FilesAndDiagonals,
    CenterControl,
    Development,
    Space,
)
from server.knowledge import (
    build_rag_query,
    format_rag_results,
    query_knowledge,
    seed_knowledge_base,
)
from server.rag import Result


def _minimal_report(**overrides) -> PositionReport:
    """Create a minimal PositionReport with sensible defaults."""
    defaults = dict(
        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        turn="white",
        fullmove_number=1,
        is_check=False,
        is_checkmate=False,
        is_stalemate=False,
        material=MaterialInfo(
            white=MaterialCount(8, 2, 2, 2, 1),
            black=MaterialCount(8, 2, 2, 2, 1),
            white_total=39, black_total=39,
            imbalance=0,
            white_bishop_pair=True, black_bishop_pair=True,
        ),
        pawn_structure=PawnStructure(white=[], black=[], white_islands=1, black_islands=1),
        king_safety_white=KingSafety(
            king_square="e1", castled="none",
            has_kingside_castling_rights=True, has_queenside_castling_rights=True,
            pawn_shield_count=3, pawn_shield_squares=["d2", "e2", "f2"],
            open_files_near_king=[], semi_open_files_near_king=[],
        ),
        king_safety_black=KingSafety(
            king_square="e8", castled="none",
            has_kingside_castling_rights=True, has_queenside_castling_rights=True,
            pawn_shield_count=3, pawn_shield_squares=["d7", "e7", "f7"],
            open_files_near_king=[], semi_open_files_near_king=[],
        ),
        activity=ActivityInfo(white=[], black=[], white_total_mobility=20, black_total_mobility=20),
        tactics=TacticalMotifs(),
        files_and_diagonals=FilesAndDiagonals(
            files=[], rooks_on_open_files=[], rooks_on_semi_open_files=[],
            bishops_on_long_diagonals=[],
        ),
        center_control=CenterControl(
            squares=[],
            white_total=2, black_total=2,
        ),
        development=Development(
            white_developed=0, black_developed=0,
            white_castled="none", black_castled="none",
        ),
        space=Space(white_squares=10, black_squares=10),
    )
    defaults.update(overrides)
    return PositionReport(**defaults)


# ---------------------------------------------------------------------------
# TestBuildRagQuery
# ---------------------------------------------------------------------------


class TestBuildRagQuery:
    def test_fork_position_mentions_fork(self):
        report = _minimal_report(
            tactics=TacticalMotifs(
                forks=[Fork(forking_square="c7", forking_piece="N", targets=["a8", "e8"])]
            )
        )
        query = build_rag_query(report, "blunder")
        assert "fork" in query.lower()

    def test_pawn_structure_issue_mentions_pawns(self):
        report = _minimal_report(
            pawn_structure=PawnStructure(
                white=[PawnDetail(square="e4", is_isolated=True)],
                black=[],
                white_islands=2, black_islands=1,
            )
        )
        query = build_rag_query(report, "inaccuracy")
        assert "pawn" in query.lower()

    def test_blunder_focuses_tactics(self):
        report = _minimal_report(
            tactics=TacticalMotifs(
                hanging=[HangingPiece(square="d5", piece="N", attacker_squares=["e4"])]
            )
        )
        query = build_rag_query(report, "blunder")
        assert "hanging" in query.lower()

    def test_blunder_with_summary_uses_summary(self):
        report = _minimal_report()
        query = build_rag_query(report, "blunder", tactics_summary="knight fork on c7")
        assert "knight fork" in query.lower()

    def test_brilliant_focuses_found_theme(self):
        report = _minimal_report()
        query = build_rag_query(report, "brilliant", tactics_summary="discovered attack wins the queen")
        assert "discovered attack" in query.lower()

    def test_inaccuracy_without_pawn_issues_falls_back(self):
        report = _minimal_report()
        query = build_rag_query(report, "inaccuracy")
        assert len(query) > 0

    def test_unknown_quality_returns_general(self):
        report = _minimal_report()
        query = build_rag_query(report, "good")
        assert "chess" in query.lower()


# ---------------------------------------------------------------------------
# TestFormatRagResults
# ---------------------------------------------------------------------------


class TestFormatRagResults:
    def test_formats_multiple_results(self):
        results = [
            Result(id="1", text="A knight fork attacks two pieces.", metadata={"theme": "tactics"}, distance=0.1),
            Result(id="2", text="Centralize your pieces early.", metadata={"theme": "opening"}, distance=0.2),
        ]
        formatted = format_rag_results(results)
        assert "[tactics]" in formatted
        assert "[opening]" in formatted
        assert "knight fork" in formatted
        assert "---" in formatted

    def test_empty_list_returns_empty_string(self):
        assert format_rag_results([]) == ""

    def test_single_result_no_delimiter(self):
        results = [
            Result(id="1", text="Pins are powerful.", metadata={"theme": "tactics"}, distance=0.1),
        ]
        formatted = format_rag_results(results)
        assert "---" not in formatted
        assert "Pins are powerful" in formatted

    def test_handles_missing_metadata(self):
        results = [
            Result(id="1", text="Some text.", metadata={}, distance=0.1),
        ]
        formatted = format_rag_results(results)
        assert "[general]" in formatted


# ---------------------------------------------------------------------------
# TestQueryKnowledge
# ---------------------------------------------------------------------------


class TestQueryKnowledge:
    async def test_returns_formatted_context(self):
        rag = AsyncMock()
        rag.query = AsyncMock(return_value=[
            Result(id="1", text="Fork concepts.", metadata={"theme": "tactics"}, distance=0.1),
        ])
        report = _minimal_report()
        result = await query_knowledge(rag, report, "blunder")
        assert "Fork concepts" in result

    async def test_rag_failure_returns_empty_string(self):
        rag = AsyncMock()
        rag.query = AsyncMock(side_effect=Exception("connection failed"))
        report = _minimal_report()
        result = await query_knowledge(rag, report, "blunder")
        assert result == ""

    async def test_empty_rag_returns_empty_string(self):
        rag = AsyncMock()
        rag.query = AsyncMock(return_value=[])
        report = _minimal_report()
        result = await query_knowledge(rag, report, "blunder")
        assert result == ""


# ---------------------------------------------------------------------------
# TestSeedKnowledgeBase
# ---------------------------------------------------------------------------


class TestSeedKnowledgeBase:
    async def test_ingests_chunks_from_json(self):
        rag = AsyncMock()
        rag.ingest = AsyncMock()

        data = [
            {"id": "t1", "text": "A fork attacks two pieces.", "metadata": {"type": "tactical", "theme": "fork"}},
            {"id": "t2", "text": "Isolated pawns are weak.", "metadata": {"type": "positional", "theme": "pawns"}},
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            count = await seed_knowledge_base(rag, f.name)

        assert count == 2
        rag.ingest.assert_called_once()
        chunks = rag.ingest.call_args[0][0]
        assert len(chunks) == 2
        assert chunks[0].id == "t1"
        assert chunks[1].id == "t2"

    async def test_empty_data_ingests_nothing(self):
        rag = AsyncMock()
        rag.ingest = AsyncMock()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([], f)
            f.flush()
            count = await seed_knowledge_base(rag, f.name)

        assert count == 0
        rag.ingest.assert_not_called()
