"""Lichess puzzle database — async SQLite queries with FTS5 theme search."""

from dataclasses import dataclass
from pathlib import Path
import random

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS puzzles (
    id         TEXT PRIMARY KEY,
    fen        TEXT NOT NULL,
    moves      TEXT NOT NULL,
    rating     INTEGER NOT NULL,
    rating_dev INTEGER NOT NULL,
    popularity INTEGER NOT NULL,
    nb_plays   INTEGER NOT NULL,
    themes     TEXT NOT NULL,
    game_url   TEXT NOT NULL,
    opening    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_puzzles_rating ON puzzles(rating);

CREATE VIRTUAL TABLE IF NOT EXISTS puzzles_fts USING fts5(
    themes, content='puzzles', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS puzzles_ai AFTER INSERT ON puzzles BEGIN
    INSERT INTO puzzles_fts(rowid, themes) VALUES (new.rowid, new.themes);
END;
CREATE TRIGGER IF NOT EXISTS puzzles_ad AFTER DELETE ON puzzles BEGIN
    INSERT INTO puzzles_fts(puzzles_fts, rowid, themes) VALUES ('delete', old.rowid, old.themes);
END;
CREATE TRIGGER IF NOT EXISTS puzzles_au AFTER UPDATE ON puzzles BEGIN
    INSERT INTO puzzles_fts(puzzles_fts, rowid, themes) VALUES ('delete', old.rowid, old.themes);
    INSERT INTO puzzles_fts(rowid, themes) VALUES (new.rowid, new.themes);
END;
"""


@dataclass
class Puzzle:
    id: str
    fen: str
    moves: list[str]
    rating: int
    rating_deviation: int
    popularity: int
    num_plays: int
    themes: list[str]
    game_url: str
    opening_tags: list[str]


def _row_to_puzzle(row: aiosqlite.Row) -> Puzzle:
    return Puzzle(
        id=row[0],
        fen=row[1],
        moves=row[2].split(),
        rating=row[3],
        rating_deviation=row[4],
        popularity=row[5],
        num_plays=row[6],
        themes=row[7].split() if row[7] else [],
        game_url=row[8],
        opening_tags=row[9].split() if row[9] else [],
    )


class PuzzleDB:
    """Async puzzle database backed by SQLite + FTS5."""

    def __init__(self, db_path: str = "data/puzzles.db"):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def start(self) -> None:
        """Open the database. No-op if the DB file doesn't exist (graceful degradation)."""
        if self._db_path == ":memory:":
            self._db = await aiosqlite.connect(":memory:")
            await self._db.executescript(SCHEMA)
            self._available = True
            return
        if not Path(self._db_path).exists():
            return
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        self._available = True

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
            self._available = False

    async def get_by_id(self, puzzle_id: str) -> Puzzle | None:
        if not self._available or not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT id, fen, moves, rating, rating_dev, popularity, nb_plays, "
            "themes, game_url, opening FROM puzzles WHERE id = ?",
            (puzzle_id,),
        )
        row = await cursor.fetchone()
        return _row_to_puzzle(row) if row else None

    def _build_query(
        self,
        select: str,
        themes: list[str] | None,
        rating_min: int | None,
        rating_max: int | None,
    ) -> tuple[str, list]:
        """Build a query with optional theme and rating filters."""
        params: list = []
        conditions: list[str] = []

        if themes:
            fts_expr = " AND ".join(themes)
            conditions.append(
                "p.rowid IN (SELECT rowid FROM puzzles_fts WHERE themes MATCH ?)"
            )
            params.append(fts_expr)

        if rating_min is not None:
            conditions.append("p.rating >= ?")
            params.append(rating_min)
        if rating_max is not None:
            conditions.append("p.rating <= ?")
            params.append(rating_max)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        return f"{select} FROM puzzles p{where}", params

    async def count(
        self,
        themes: list[str] | None = None,
        rating_min: int | None = None,
        rating_max: int | None = None,
    ) -> int:
        if not self._available or not self._db:
            return 0
        query, params = self._build_query("SELECT COUNT(*)", themes, rating_min, rating_max)
        cursor = await self._db.execute(query, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_random(
        self,
        themes: list[str] | None = None,
        rating_min: int | None = None,
        rating_max: int | None = None,
        limit: int = 1,
    ) -> list[Puzzle]:
        if not self._available or not self._db:
            return []
        total = await self.count(themes, rating_min, rating_max)
        if total == 0:
            return []

        results: list[Puzzle] = []
        seen_offsets: set[int] = set()
        attempts = 0
        max_attempts = limit * 3

        while len(results) < limit and attempts < max_attempts:
            offset = random.randint(0, total - 1)
            if offset in seen_offsets:
                attempts += 1
                continue
            seen_offsets.add(offset)
            attempts += 1

            query, params = self._build_query(
                "SELECT p.id, p.fen, p.moves, p.rating, p.rating_dev, p.popularity, "
                "p.nb_plays, p.themes, p.game_url, p.opening",
                themes, rating_min, rating_max,
            )
            query += " LIMIT 1 OFFSET ?"
            params.append(offset)

            cursor = await self._db.execute(query, params)
            row = await cursor.fetchone()
            if row:
                results.append(_row_to_puzzle(row))

        return results
