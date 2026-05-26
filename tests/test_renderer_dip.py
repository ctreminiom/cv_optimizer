"""Tests for DIP-fixed renderer functions — injectable LLM client."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.report.renderer import (
    _generate_strategic_insights,
    _company_costa_rica_blurb,
    _generate_cv_proposal_with_opus,
)


def _mock_client(response: str) -> MagicMock:
    m = MagicMock()
    m.complete.return_value = response
    return m


def test_generate_strategic_insights_uses_injected_client() -> None:
    payload = json.dumps({"career_narrative": "Strong backend track."})
    client = _mock_client(payload)
    result = _generate_strategic_insights({}, client=client)
    client.complete.assert_called_once()
    assert result.get("career_narrative") == "Strong backend track."


def test_generate_strategic_insights_returns_empty_on_client_error() -> None:
    bad_client = MagicMock()
    bad_client.complete.side_effect = RuntimeError("API down")
    result = _generate_strategic_insights({}, client=bad_client)
    assert result == {}


def test_company_costa_rica_blurb_uses_injected_client() -> None:
    client = _mock_client("Intel has operated in Costa Rica since 1997.")
    result = _company_costa_rica_blurb("Intel", client=client)
    client.complete.assert_called_once()
    assert "Intel" in result or "Costa Rica" in result


def test_company_costa_rica_blurb_caches_result() -> None:
    import src.report.renderer as rmod
    rmod._CR_BLURB_CACHE.pop("CacheTestCo", None)

    client = _mock_client("CacheTestCo has a small CR office.")
    _company_costa_rica_blurb("CacheTestCo", client=client)
    _company_costa_rica_blurb("CacheTestCo", client=client)
    # Second call should be served from cache — client called only once.
    assert client.complete.call_count == 1
    rmod._CR_BLURB_CACHE.pop("CacheTestCo", None)


def test_generate_cv_proposal_returns_empty_on_client_error() -> None:
    bad_client = MagicMock()
    bad_client.complete.side_effect = RuntimeError("Opus unavailable")
    result = _generate_cv_proposal_with_opus({}, client=bad_client)
    assert result == {}
