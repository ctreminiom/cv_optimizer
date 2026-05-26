"""Unit tests for pydantic-settings configuration (B5)."""
from __future__ import annotations

import importlib

import pytest


def test_settings_loads_required_anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    # Force a fresh load
    import src.settings as s
    importlib.reload(s)
    cfg = s.Settings()  # type: ignore[call-arg]
    assert cfg.reveal(cfg.anthropic_api_key) == "sk-ant-test-123"
    assert cfg.model_haiku.startswith("claude-")
    assert cfg.embeddings_provider in {"local", "voyage", "openai"}


def test_settings_raises_when_required_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir("/tmp")  # avoid picking up a real .env
    import src.settings as s
    importlib.reload(s)
    with pytest.raises(Exception):
        s.Settings()  # type: ignore[call-arg]


def test_optional_keys_default_to_none(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    # chdir to an empty dir so the real .env is not picked up
    monkeypatch.chdir(tmp_path)
    import src.settings as s
    importlib.reload(s)
    cfg = s.Settings()  # type: ignore[call-arg]
    assert cfg.tavily_api_key is None
    assert cfg.serper_api_key is None
