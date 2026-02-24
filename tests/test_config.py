"""Tests for centralized configuration."""

import os
import pytest
from pydantic import ValidationError
from server.config import Settings


class TestSettings:
    def test_required_fields_missing(self, monkeypatch):
        """App fails clearly if LLM_BASE_URL or LLM_MODEL not set."""
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_minimal_config(self, monkeypatch):
        """Only LLM_BASE_URL and LLM_MODEL are required."""
        monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setenv("LLM_MODEL", "qwen2.5:14b")
        s = Settings(_env_file=None)
        assert s.llm_base_url == "http://localhost:11434"
        assert s.llm_model == "qwen2.5:14b"
        assert s.llm_api_key is None
        assert s.stockfish_hash_mb == 64

    def test_embed_base_url_falls_back_to_llm(self, monkeypatch):
        """When EMBED_BASE_URL is not set, use LLM_BASE_URL."""
        monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setenv("LLM_MODEL", "qwen2.5:14b")
        s = Settings(_env_file=None)
        assert s.embed_base_url is None
        assert s.effective_embed_base_url == "http://localhost:11434"

    def test_embed_base_url_override(self, monkeypatch):
        """When EMBED_BASE_URL is set, it takes precedence."""
        monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setenv("LLM_MODEL", "qwen2.5:14b")
        monkeypatch.setenv("EMBED_BASE_URL", "https://api.together.xyz")
        s = Settings(_env_file=None)
        assert s.effective_embed_base_url == "https://api.together.xyz"

    def test_embed_api_key_falls_back_to_llm(self, monkeypatch):
        """When EMBED_API_KEY is not set, use LLM_API_KEY."""
        monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
        monkeypatch.setenv("LLM_MODEL", "qwen2.5:14b")
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        s = Settings(_env_file=None)
        assert s.effective_embed_api_key == "sk-test"

    def test_all_fields(self, monkeypatch):
        """All fields can be set explicitly."""
        monkeypatch.setenv("LLM_BASE_URL", "https://openrouter.ai/api")
        monkeypatch.setenv("LLM_MODEL", "qwen/qwen-2.5-coder-32b")
        monkeypatch.setenv("LLM_API_KEY", "sk-or-xxx")
        monkeypatch.setenv("LLM_TIMEOUT", "60.0")
        monkeypatch.setenv("EMBED_BASE_URL", "https://api.together.xyz")
        monkeypatch.setenv("EMBED_MODEL", "togethercomputer/m2-bert")
        monkeypatch.setenv("EMBED_API_KEY", "sk-tog-xxx")
        monkeypatch.setenv("STOCKFISH_PATH", "/usr/games/stockfish")
        monkeypatch.setenv("STOCKFISH_HASH_MB", "256")
        monkeypatch.setenv("CHROMADB_DIR", "/data/chromadb")
        monkeypatch.setenv("PUZZLE_DB_PATH", "/data/puzzles.db")
        monkeypatch.setenv("AUTO_INIT_PUZZLES", "false")
        s = Settings(_env_file=None)
        assert s.llm_timeout == 60.0
        assert s.stockfish_hash_mb == 256
        assert s.auto_init_puzzles is False
