"""CLI: Import Lichess puzzle database into SQLite.

Usage:
    python -m server.import_puzzles                           # download + import
    python -m server.import_puzzles --csv-path puzzles.csv.zst  # local file
"""

import argparse
import csv
import io
import sqlite3
import sys
import time
from pathlib import Path

import zstandard

LICHESS_PUZZLE_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
DB_PATH = "data/puzzles.db"
BATCH_SIZE = 5000

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
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS puzzles_fts USING fts5(
    themes, content='puzzles', content_rowid='rowid'
);
"""

TRIGGERS = """
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

INSERT_SQL = """
INSERT OR REPLACE INTO puzzles (id, fen, moves, rating, rating_dev, popularity, nb_plays, themes, game_url, opening)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def create_db(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.executescript(FTS_SCHEMA)
    # Drop triggers during bulk import for speed
    for trigger in ("puzzles_ai", "puzzles_ad", "puzzles_au"):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    conn.commit()
    return conn


def stream_csv_from_zst(path: str):
    """Yield CSV rows from a .csv.zst file using streaming decompression."""
    dctx = zstandard.ZstdDecompressor()
    with open(path, "rb") as fh:
        with dctx.stream_reader(fh) as reader:
            text_stream = io.TextIOWrapper(reader, encoding="utf-8")
            yield from csv.reader(text_stream)


def download_and_stream_csv(url: str):
    """Stream-download and decompress a .csv.zst URL. Yields CSV rows."""
    import urllib.request

    dctx = zstandard.ZstdDecompressor()
    req = urllib.request.Request(url, headers={"User-Agent": "chess-teacher-importer/1.0"})
    with urllib.request.urlopen(req) as resp:
        with dctx.stream_reader(resp) as reader:
            text_stream = io.TextIOWrapper(reader, encoding="utf-8")
            yield from csv.reader(text_stream)


def parse_row(row: list[str]) -> tuple | None:
    """Parse a CSV row into a tuple for INSERT. Returns None for header/invalid rows."""
    if len(row) < 9:
        return None
    puzzle_id, fen, moves, rating, rating_dev, popularity, nb_plays, themes, game_url = row[:9]
    opening = row[9] if len(row) > 9 else ""
    try:
        return (
            puzzle_id,
            fen,
            moves,
            int(rating),
            int(rating_dev),
            int(popularity),
            int(nb_plays),
            themes,
            game_url,
            opening,
        )
    except ValueError:
        return None


def import_puzzles(conn: sqlite3.Connection, rows, verbose: bool = True) -> int:
    """Batch-insert parsed rows into the database. Returns count of rows inserted."""
    batch: list[tuple] = []
    count = 0
    t0 = time.time()

    for row in rows:
        parsed = parse_row(row)
        if parsed is None:
            continue
        batch.append(parsed)
        if len(batch) >= BATCH_SIZE:
            conn.executemany(INSERT_SQL, batch)
            conn.commit()
            count += len(batch)
            batch.clear()
            if verbose and count % 100_000 == 0:
                elapsed = time.time() - t0
                rate = count / elapsed if elapsed > 0 else 0
                print(f"  {count:,} rows ({rate:,.0f} rows/sec)")

    if batch:
        conn.executemany(INSERT_SQL, batch)
        conn.commit()
        count += len(batch)

    return count


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild FTS index after bulk import."""
    print("Rebuilding FTS index...")
    conn.execute("INSERT INTO puzzles_fts(puzzles_fts) VALUES('rebuild')")
    conn.commit()


def finalize_db(conn: sqlite3.Connection) -> None:
    """Add triggers and rebuild FTS after bulk import."""
    rebuild_fts(conn)
    conn.executescript(TRIGGERS)
    conn.commit()
    print("Triggers restored.")


def main():
    parser = argparse.ArgumentParser(description="Import Lichess puzzles into SQLite")
    parser.add_argument("--csv-path", help="Path to local .csv.zst file (skip download)")
    parser.add_argument("--db-path", default=DB_PATH, help=f"SQLite database path (default: {DB_PATH})")
    args = parser.parse_args()

    print(f"Database: {args.db_path}")
    conn = create_db(args.db_path)

    try:
        if args.csv_path:
            print(f"Importing from {args.csv_path}...")
            rows = stream_csv_from_zst(args.csv_path)
        else:
            print(f"Downloading from {LICHESS_PUZZLE_URL}...")
            rows = download_and_stream_csv(LICHESS_PUZZLE_URL)

        t0 = time.time()
        count = import_puzzles(conn, rows)
        elapsed = time.time() - t0
        print(f"Imported {count:,} puzzles in {elapsed:.1f}s")

        finalize_db(conn)
        print("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
