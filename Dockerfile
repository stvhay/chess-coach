FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends stockfish && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen
# Patch chromadb config.py for Python 3.14 + pydantic v2 compatibility
COPY patches/chromadb_config.py.patch /tmp/chromadb_config.py.patch
RUN python /tmp/chromadb_config.py.patch
COPY src/ src/
COPY static/ static/
COPY data/knowledge_base.json /app/data/knowledge_base.json
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && mkdir -p data
ENV STOCKFISH_PATH=/usr/games/stockfish
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uv", "run", "uvicorn", "server.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
