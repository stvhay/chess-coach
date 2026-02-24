import os

# Settings requires these env vars at import time
os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434")
os.environ.setdefault("LLM_MODEL", "test-model")

from fastapi.testclient import TestClient
from server.main import app


client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
