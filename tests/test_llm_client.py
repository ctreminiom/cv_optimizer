"""Tests for the LLM client abstraction layer (Phase 2).

The key property: every function that calls the Anthropic API accepts an
injected `client` parameter so tests never touch the network.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.client import LLMClientProtocol, _AnthropicClient, get_default_client


# ── Shared test double ──────────────────────────────────────────────────────

class _MockClient:
    """Minimal LLMClientProtocol implementation; records calls for assertions."""

    def __init__(self, response: str = "ok") -> None:
        self.calls: list[dict] = []
        self._response = response

    def complete(self, *, model: str, max_tokens: int,
                 messages: list) -> str:
        self.calls.append({"model": model, "max_tokens": max_tokens,
                           "messages": messages})
        return self._response


# ── Protocol conformance ────────────────────────────────────────────────────

def test_mock_client_satisfies_protocol() -> None:
    assert isinstance(_MockClient(), LLMClientProtocol)


def test_anthropic_client_satisfies_protocol() -> None:
    fake = MagicMock()
    with patch("anthropic.Anthropic", return_value=fake):
        c = _AnthropicClient(api_key="key")
    assert isinstance(c, LLMClientProtocol)


# ── _AnthropicClient unit tests ─────────────────────────────────────────────

def test_anthropic_client_wraps_create() -> None:
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text="hello")]
    fake_sdk = MagicMock()
    fake_sdk.messages.create.return_value = fake_resp

    with patch("anthropic.Anthropic", return_value=fake_sdk):
        c = _AnthropicClient(api_key="test-key")
        result = c.complete(
            model="haiku",
            max_tokens=100,
            messages=[{"role": "user", "content": "hi"}],
        )

    assert result == "hello"
    fake_sdk.messages.create.assert_called_once_with(
        model="haiku",
        max_tokens=100,
        messages=[{"role": "user", "content": "hi"}],
    )


def test_anthropic_client_empty_content_returns_empty_string() -> None:
    fake_resp = MagicMock()
    fake_resp.content = []
    fake_sdk = MagicMock()
    fake_sdk.messages.create.return_value = fake_resp

    with patch("anthropic.Anthropic", return_value=fake_sdk):
        c = _AnthropicClient(api_key="key")
        assert c.complete(model="m", max_tokens=10, messages=[]) == ""


# ── Injection tests — call sites use the injected client ───────────────────

def test_extract_job_info_uses_injected_client() -> None:
    from src.tools.job_parser import _extract_job_info_with_claude

    payload = json.dumps({
        "title": "Software Engineer",
        "company": "Acme Corp",
        "location": "Remote",
        "modality": "remote",
        "seniority": "senior",
        "salary_range": None,
        "role_type": "backend_engineer",
        "tech_stack": ["Go", "Kubernetes"],
        "ats_keywords": ["Go", "Kubernetes", "gRPC"],
    })
    mock = _MockClient(response=payload)

    result = _extract_job_info_with_claude("some job text", client=mock)

    assert result["title"] == "Software Engineer"
    assert result["company"] == "Acme Corp"
    assert len(mock.calls) == 1


def test_extract_job_info_returns_empty_on_client_failure() -> None:
    from src.tools.job_parser import _extract_job_info_with_claude

    class _BrokenClient:
        def complete(self, **_kw) -> str:
            raise RuntimeError("network error")

    result = _extract_job_info_with_claude("text", client=_BrokenClient())
    assert result == {}


def test_llm_judge_uses_injected_client() -> None:
    from src.search_pipeline import llm_judge

    verdict = json.dumps({
        "role_match": {"pass": 1, "reason": "ok"},
        "seniority_match": {"pass": 1, "reason": "ok"},
        "modality_match": {"pass": 1, "reason": "ok"},
        "location_match": {"pass": 1, "reason": "ok"},
        "fails_count": 0,
    })
    mock = _MockClient(response=verdict)
    ops = [{"title": "Backend Eng", "company": "X", "location": "Remote",
            "modality": "remote", "url": "https://x.com/1"}]

    result = llm_judge(
        ops,
        target_role="backend engineer",
        target_seniority=None,
        target_modality="remote",
        target_location="any",
        client=mock,
    )

    assert len(result) == 1
    assert result[0]["judge_verdict"]["fails_count"] == 0
    assert len(mock.calls) == 1


def test_llm_judge_keeps_opportunity_on_client_error() -> None:
    from src.search_pipeline import llm_judge

    class _BrokenClient:
        def complete(self, **_kw) -> str:
            raise RuntimeError("timeout")

    ops = [{"title": "Dev", "company": "Y", "url": "https://y.com/1"}]
    result = llm_judge(
        ops,
        target_role="developer",
        target_seniority=None,
        target_modality=None,
        target_location="any",
        client=_BrokenClient(),
    )
    assert result == ops


def test_llm_judge_falls_back_when_no_client_available() -> None:
    """When get_default_client() raises (no API key), opportunities pass through."""
    from src.search_pipeline import llm_judge

    ops = [{"title": "Dev", "company": "Y", "url": "https://y.com/1"}]
    with patch("src.llm.client.get_default_client",
               side_effect=Exception("no key")):
        result = llm_judge(
            ops,
            target_role="developer",
            target_seniority=None,
            target_modality=None,
            target_location="any",
        )
    assert result == ops


# ── get_default_client factory ──────────────────────────────────────────────

def test_get_default_client_raises_on_settings_failure() -> None:
    """get_default_client propagates any exception from get_settings().

    get_settings is imported inline inside get_default_client, so patch
    the singleton at its canonical location.
    """
    with patch("src.settings.get_settings",
               side_effect=ValueError("ANTHROPIC_API_KEY missing")):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY missing"):
            get_default_client()
