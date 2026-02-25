# Deploying Chess Coach

## Environment Variables

All optional. Defaults match the development setup. See `.env.example` for the complete reference.

### LLM and Embedding Configuration

| Variable            | Default                    | Purpose                         |
|---------------------|----------------------------|---------------------------------|
| `LLM_BASE_URL`      | (required)                 | OpenAI-compatible API base URL  |
| `LLM_MODEL`         | (required)                 | Model name for coaching         |
| `LLM_API_KEY`       | (optional)                 | Bearer token for LLM auth       |
| `LLM_TIMEOUT`       | `30.0`                     | LLM request timeout in seconds  |
| `EMBED_BASE_URL`    | (inherits `LLM_BASE_URL`)  | Embedding API base URL          |
| `EMBED_MODEL`       | `nomic-embed-text`         | Embedding model for RAG         |
| `EMBED_API_KEY`     | (inherits `LLM_API_KEY`)   | Bearer token for embedding auth |

### Data and Storage

| Variable            | Default                    | Purpose                         |
|---------------------|----------------------------|---------------------------------|
| `CHROMADB_DIR`      | `data/chromadb`            | ChromaDB persistence directory  |
| `PUZZLE_DB_PATH`    | `data/puzzles.db`          | Puzzle SQLite database path     |
| `RAG_TOP_K`         | `3`                        | Number of RAG chunks to retrieve (0 = disabled) |
| `AUTO_INIT_PUZZLES` | `true`                     | Download puzzles from Lichess on first boot |

### Engine Configuration

| Variable            | Default                    | Purpose                         |
|---------------------|----------------------------|---------------------------------|
| `STOCKFISH_PATH`    | `stockfish`[^1]            | Path to Stockfish binary        |
| `STOCKFISH_HASH_MB` | `64`                       | Stockfish hash table size in MB |

### Experimental Features

| Variable                            | Default | Purpose                                    |
|-------------------------------------|---------|-------------------------------------------|
| `CHESS_TEACHER_ENABLE_CHAINING`     | `0`     | Enable Tier 1 tactical chain detection (pin→hanging) |
| `CHESS_TEACHER_ENABLE_TIER2_CHAINS` | `0`     | Enable Tier 2 chains (overload→hanging, capturable-defender→hanging) |

### Server Binding (Docker Compose)

| Variable       | Default       | Purpose                     |
|----------------|---------------|-----------------------------|
| `LISTEN_ADDR`  | `127.0.0.1`   | Bind address                |
| `PORT`         | `8000`        | Host port                   |

[^1]: Set to `/usr/games/stockfish` in Docker

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

