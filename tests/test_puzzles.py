"""Tests for the puzzle database module."""

import pytest

from server.puzzles import Puzzle, PuzzleDB

# Sample puzzle data for testing
SAMPLE_PUZZLES = [
    ("00sHx", "r4rk1/pp3ppp/2n1b3/q3N3/2B5/2P2Q2/P4PPP/3RR1K1 w - - 3 18",
     "f3f7 g8h8 f7f6 h8g8 e5g6", 1704, 74, 96, 42890,
     "advantage fork middlegame short", "https://lichess.org/F8M8OS71#35",
     "Italian_Game Italian_Game_Classical_Variation"),
    ("00sOl", "4r1k1/1p3pp1/p1p2n1p/8/P1b1PR2/2P2N1P/1P4P1/4R1K1 w - - 0 24",
     "f4f6 g7f6 e1e8 f6f5", 1210, 75, 97, 57653,
     "advantage endgame short", "https://lichess.org/5mEBVnbp#47", ""),
    ("00tBD", "r1b2rk1/pppp1ppp/2n2n2/1Bb1N3/4P3/2P5/PP3PPP/RNBQ1RK1 b - - 0 7",
     "c6e5 d1h5 g7g6 h5e5", 1346, 76, 95, 30140,
     "advantage middlegame short", "https://lichess.org/cIzmFhMh#14", ""),
    ("00yXJ", "8/1p3k2/p3pp2/4b3/P3P3/1P1R1P2/2r3PP/5K2 w - - 2 30",
     "d3d7 b7b5 d7a7 e5c3", 1434, 78, 88, 9083,
     "endgame short", "https://lichess.org/GJ0sPNCR/black#59", ""),
    ("01A3R", "r2qkbnr/pp1bpppp/2n5/1B2N3/3p4/8/PPPP1PPP/RNBQK2R w KQkq - 0 5",
     "e5c6 b7c6 b5c6 d7c6", 1043, 81, 93, 11506,
     "advantage opening short", "https://lichess.org/jkbn44EU#9",
     "Scotch_Game Scotch_Game_Schmidt_Variation"),
    # Fork-themed puzzles for theme filtering
    ("fork1", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
     "e2e4 e7e5", 800, 70, 90, 1000,
     "fork short", "https://lichess.org/test1", ""),
    ("fork2", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
     "d2d4 d7d5", 1500, 70, 90, 2000,
     "fork endgame", "https://lichess.org/test2", ""),
]


async def _create_populated_db() -> PuzzleDB:
    """Create an in-memory PuzzleDB with sample data."""
    db = PuzzleDB(db_path=":memory:")
    await db.start()
    assert db._db is not None
    for row in SAMPLE_PUZZLES:
        await db._db.execute(
            "INSERT INTO puzzles (id, fen, moves, rating, rating_dev, popularity, "
            "nb_plays, themes, game_url, opening) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
    await db._db.commit()
    return db


@pytest.fixture
async def puzzle_db():
    db = await _create_populated_db()
    yield db
    await db.close()


class TestPuzzleDB:
    async def test_start_missing_file(self, tmp_path):
        """start() is a no-op when db file doesn't exist."""
        db = PuzzleDB(db_path=str(tmp_path / "nonexistent.db"))
        await db.start()
        assert not db.available
        assert await db.get_by_id("anything") is None
        assert await db.count() == 0
        assert await db.get_random() == []

    async def test_start_memory(self):
        db = PuzzleDB(db_path=":memory:")
        await db.start()
        assert db.available
        await db.close()

    async def test_get_by_id(self, puzzle_db: PuzzleDB):
        puzzle = await puzzle_db.get_by_id("00sHx")
        assert puzzle is not None
        assert puzzle.id == "00sHx"
        assert puzzle.rating == 1704
        assert puzzle.moves == ["f3f7", "g8h8", "f7f6", "h8g8", "e5g6"]
        assert "fork" in puzzle.themes
        assert "middlegame" in puzzle.themes
        assert puzzle.opening_tags == ["Italian_Game", "Italian_Game_Classical_Variation"]

    async def test_get_by_id_not_found(self, puzzle_db: PuzzleDB):
        puzzle = await puzzle_db.get_by_id("nonexistent")
        assert puzzle is None

    async def test_count_all(self, puzzle_db: PuzzleDB):
        count = await puzzle_db.count()
        assert count == len(SAMPLE_PUZZLES)

    async def test_count_with_rating_filter(self, puzzle_db: PuzzleDB):
        count = await puzzle_db.count(rating_min=1000, rating_max=1400)
        # 00sOl(1210), 00tBD(1346), 01A3R(1043) = 3
        assert count == 3

    async def test_count_with_theme_filter(self, puzzle_db: PuzzleDB):
        count = await puzzle_db.count(themes=["fork"])
        # 00sHx, fork1, fork2 = 3
        assert count == 3

    async def test_count_with_theme_and_rating(self, puzzle_db: PuzzleDB):
        count = await puzzle_db.count(themes=["fork"], rating_min=1000, rating_max=1800)
        # 00sHx(1704), fork2(1500) = 2
        assert count == 2

    async def test_count_multiple_themes(self, puzzle_db: PuzzleDB):
        count = await puzzle_db.count(themes=["fork", "endgame"])
        # fork2 has both "fork" and "endgame" = 1
        assert count == 1

    async def test_get_random_returns_puzzle(self, puzzle_db: PuzzleDB):
        results = await puzzle_db.get_random(limit=1)
        assert len(results) == 1
        assert isinstance(results[0], Puzzle)

    async def test_get_random_with_filters(self, puzzle_db: PuzzleDB):
        results = await puzzle_db.get_random(themes=["fork"], rating_min=700, rating_max=900, limit=1)
        assert len(results) == 1
        assert results[0].id == "fork1"

    async def test_get_random_multiple(self, puzzle_db: PuzzleDB):
        results = await puzzle_db.get_random(limit=3)
        assert len(results) == 3
        ids = {p.id for p in results}
        assert len(ids) == 3  # all unique

    async def test_get_random_limit_exceeds_available(self, puzzle_db: PuzzleDB):
        results = await puzzle_db.get_random(themes=["fork", "endgame"], limit=5)
        # Only fork2 matches both themes
        assert len(results) == 1
        assert results[0].id == "fork2"

    async def test_get_random_no_matches(self, puzzle_db: PuzzleDB):
        results = await puzzle_db.get_random(themes=["nonexistent"])
        assert results == []

    async def test_puzzle_fields(self, puzzle_db: PuzzleDB):
        puzzle = await puzzle_db.get_by_id("00sOl")
        assert puzzle is not None
        assert puzzle.fen == "4r1k1/1p3pp1/p1p2n1p/8/P1b1PR2/2P2N1P/1P4P1/4R1K1 w - - 0 24"
        assert puzzle.rating_deviation == 75
        assert puzzle.popularity == 97
        assert puzzle.num_plays == 57653
        assert puzzle.themes == ["advantage", "endgame", "short"]
        assert puzzle.game_url == "https://lichess.org/5mEBVnbp#47"
        assert puzzle.opening_tags == []

    async def test_close(self, puzzle_db: PuzzleDB):
        assert puzzle_db.available
        await puzzle_db.close()
        assert not puzzle_db.available


class TestImportPuzzles:
    """Tests for the import module's parse_row function."""

    def test_parse_row_valid(self):
        from server.import_puzzles import parse_row

        row = ["abc", "fen", "e2e4 e7e5", "1200", "75", "90", "5000", "fork short", "https://url", "Italian"]
        result = parse_row(row)
        assert result == ("abc", "fen", "e2e4 e7e5", 1200, 75, 90, 5000, "fork short", "https://url", "Italian")

    def test_parse_row_no_opening(self):
        from server.import_puzzles import parse_row

        row = ["abc", "fen", "e2e4", "1200", "75", "90", "5000", "fork", "https://url"]
        result = parse_row(row)
        assert result is not None
        assert result[9] == ""

    def test_parse_row_too_short(self):
        from server.import_puzzles import parse_row

        row = ["abc", "fen"]
        assert parse_row(row) is None

    def test_parse_row_header(self):
        from server.import_puzzles import parse_row

        row = ["PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation", "Popularity", "NbPlays", "Themes", "GameUrl"]
        assert parse_row(row) is None
