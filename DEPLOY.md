# Deploying Chess Teacher

## Architecture

```
Users -> Caddy/NPM (dedi) -> chess-teacher container (port 8000)
                                  +-- FastAPI + Stockfish + static frontend
                                  +-- ChromaDB (/app/data volume)
                                  +-- SQLite puzzles (/app/data volume)
                                       |
                                  (Tailscale VPN)
                                       |
                                Knuth -> Ollama (4070 Ti)
```

Single container on the dedi. Ollama stays on knuth, reached over Tailscale.

## Environment Variables

All optional. Defaults match the development setup.

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_URL` | `https://ollama.st5ve.com` | Ollama API endpoint |
| `CHROMADB_DIR` | `data/chromadb` | ChromaDB storage path |
| `PUZZLE_DB_PATH` | `data/puzzles.db` | Puzzle SQLite database path |
| `STOCKFISH_HASH_MB` | `64` | Stockfish hash table size in MB |

## Initial Deploy

```bash
git clone git@github.com:stvhay/chess-coach.git chess-teacher
cd chess-teacher
```

Edit `docker-compose.yml` and replace `<knuth-tailscale-ip>` with the actual Tailscale IP or hostname for knuth. Alternatively, keep `https://ollama.st5ve.com` if the public endpoint works.

```bash
docker compose up -d --build
```

The first startup seeds the ChromaDB knowledge base automatically (takes ~30 seconds).

## Reverse Proxy

The container binds to `127.0.0.1:8000`. Put a reverse proxy in front of it.

**Caddy:**
```
chess.domain.com {
    reverse_proxy localhost:8000
}
```

**Nginx Proxy Manager:** Create a new proxy host pointing to `http://127.0.0.1:8000` and enable SSL.

FastAPI sets `Cross-Origin-Embedder-Policy` and `Cross-Origin-Opener-Policy` headers on all responses. Verify the reverse proxy doesn't strip them (check browser devtools Network tab).

## Puzzle Database (one-time)

After the container is running, import the Lichess puzzle database:

```bash
docker exec chess-teacher uv run python -m server.import_puzzles --db-path /app/data/puzzles.db
docker restart chess-teacher
```

This downloads ~100MB compressed from Lichess and imports 5.7M puzzles. Takes 5-10 minutes.

## Updates

```bash
cd chess-teacher && git pull && docker compose up -d --build
```

Data persists in the `chess-data` Docker volume across rebuilds.

## Verification

1. Health check: `curl http://localhost:8000/api/health` returns `{"status":"ok"}`
2. Root redirect: `curl -L http://localhost:8000/` returns index.html
3. Browser: visit the public URL, confirm COEP/COOP headers in devtools
4. Start a new game to verify Ollama connectivity

## Troubleshooting

**ChromaDB build failure:** The `uv.lock` pins working versions. If a chromadb import error appears during build, check for Python 3.14 compatibility issues with pydantic v1.

**Ollama unreachable:** The container uses Docker's default bridge network. The host's Tailscale interface is reachable from inside the container. If not, either use `network_mode: host` in docker-compose.yml or use the public `https://ollama.st5ve.com` endpoint.

**RAM:** FastAPI + Stockfish + ChromaDB uses ~1-2GB. The dedi has ~3.8GB free.
