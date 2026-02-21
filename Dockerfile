FROM python:3.14-slim

RUN apt-get update && apt-get install -y stockfish && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --no-dev

COPY src/ src/
COPY static/ static/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "server.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
