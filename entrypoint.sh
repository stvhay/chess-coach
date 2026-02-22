#!/bin/sh
set -e
cp -n /app/knowledge_base.json /app/data/knowledge_base.json 2>/dev/null || true
if [ ! -f /app/data/chromadb/chroma.sqlite3 ]; then
    echo "Seeding knowledge base..."
    cd /app && uv run python -m server.seed_knowledge
fi
exec "$@"
