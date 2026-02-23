# Deploying Chess Coach

## Environment Variables

All optional. Defaults match the development setup.

| Variable            | Default                    | Purpose                         |
|---------------------| ---------------------------|---------------------------------|
| `OLLAMA_URL`        | `https://ollama.st5ve.com` | Ollama API endpoint             |
| `CHROMADB_DIR`      | `data/chromadb`            | ChromaDB storage path           |
| `PUZZLE_DB_PATH`    | `data/puzzles.db`          | Puzzle SQLite database path     |
| `STOCKFISH_HASH_MB` | `64`                       | Stockfish hash table size in MB |
| `STOCKFISH_PATH`    | `stockfish`                | Path to Stockfish binary        |

[^1]: Set to `/usr/games/stockfish` in Docker)

## Deploy

```bash
git clone https://github.com/stvhay/chess-coach.git chess-coach
# Set up docker-compose.yaml
docker compose build chess-coach
docker compose up -d chess-coach
```

_Note: The first startup seeds the ChromaDB knowledge base automatically (takes ~30 seconds)._

### Puzzle Database (one-time)

After the container is running, import the Lichess puzzle database:

```bash
docker exec chess-coach uv run python -m server.import_puzzles --db-path /app/data/puzzles.db
docker restart chess-coach
```

This downloads ~100MB compressed from Lichess and imports 5.7M puzzles. Takes 5-10 minutes.

## Reverse Proxy

**Caddy:**
```
chess-teacher.domain.com {
    reverse_proxy chess-coach:8000
}
```

## Updates

```bash
git pull && docker compose up -d --build
```

Data persists in the `chess-data` Docker volume across rebuilds.

## Health Check

`curl http://localhost:8000/api/health` returns `{"status":"ok"}`

