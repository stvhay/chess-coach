"""Tests for initialization status tracking."""

import os

os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434")
os.environ.setdefault("LLM_MODEL", "test-model")

from server.main import _init_status, _set_status, _all_done


class TestInitStatus:
    def setup_method(self):
        """Reset status before each test."""
        for key in _init_status:
            _init_status[key] = {"state": "pending", "detail": ""}

    def test_all_pending_not_ready(self):
        assert _all_done() is False

    def test_all_done_is_ready(self):
        for key in _init_status:
            _set_status(key, "done")
        assert _all_done() is True

    def test_mixed_states_not_ready(self):
        _set_status("stockfish", "done")
        _set_status("chromadb", "running", "Seeding...")
        _set_status("puzzles", "pending")
        assert _all_done() is False

    def test_failed_counts_as_done(self):
        """Failed tasks don't block readiness -- they degrade gracefully."""
        _set_status("stockfish", "done")
        _set_status("chromadb", "done")
        _set_status("puzzles", "failed", "Network error")
        assert _all_done() is True

    def test_set_status_updates(self):
        _set_status("puzzles", "running", "Downloading (1.2M rows)...")
        assert _init_status["puzzles"]["state"] == "running"
        assert _init_status["puzzles"]["detail"] == "Downloading (1.2M rows)..."
