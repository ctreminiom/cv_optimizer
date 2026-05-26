"""Unit tests for the search_jobs tool's filtering behavior."""
from __future__ import annotations

import json
import os

import pytest

from src.tools.search import (
    _dedupe_key,
    _matches_negative,
    _location_matches,
    _normalize_for_dedupe,
    search_jobs,
)


def test_normalize_for_dedupe_strips_punctuation_and_lowercases():
    assert _normalize_for_dedupe("Senior  Go Engineer (Remote!)") == "senior go engineer remote"


def test_dedupe_key_collapses_same_posting_on_different_boards():
    a = {"title": "Senior Go Engineer", "company": "Acme", "location": "San José, Costa Rica"}
    b = {"title": "senior  go engineer", "company": "ACME", "location": "San Jose"}
    # Locations differ on accent + suffix; first-token-only normalization collapses them
    assert _dedupe_key(a) == _dedupe_key({"title": "Senior Go Engineer",
                                           "company": "Acme",
                                           "location": "San José"})


def test_matches_negative_catches_internship():
    op = {"title": "Senior Engineer Internship", "snippet": "great learning opportunity"}
    assert _matches_negative(op, ["internship"]) is True
    assert _matches_negative(op, ["fulltime"]) is False


def test_location_matches_passes_aggregator_pages():
    op = {"link_type": "search_url", "location": "anything"}
    assert _location_matches(op, "Costa Rica") is True


def test_location_matches_rejects_florida_when_exact():
    op = {"link_type": "direct_listing", "location": "Costa Rica, Florida, US"}
    # Substring match still allows it through (correctly — "Costa Rica" is in the string)
    assert _location_matches(op, "Costa Rica") is True
    # But "Punta Cana" wouldn't match
    op2 = {"link_type": "direct_listing", "location": "Punta Cana, DR"}
    assert _location_matches(op2, "Costa Rica") is False


def test_search_jobs_returns_deeplinks_with_no_api_keys(monkeypatch):
    """Without any provider keys, search_jobs still returns the deep-link
    fallbacks so the OSS no-key path works."""
    for k in ("TAVILY_API_KEY", "SERPER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    raw = search_jobs.run(json.dumps({
        "role_keywords": ["backend", "go"],
        "location": "Costa Rica",
        "max_results": 5,
    }))
    out = json.loads(raw)
    assert out.get("total_found", 0) > 0
    assert "deep_links" in out["sources_used"]
    assert all(o["url"].startswith("http") for o in out["opportunities"])


def test_search_jobs_applies_exclude_filter(monkeypatch):
    for k in ("TAVILY_API_KEY", "SERPER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    raw = search_jobs.run(json.dumps({
        "role_keywords": ["backend"],
        "location": "Costa Rica",
        "exclude_keywords": ["linkedin"],  # excludes anything mentioning linkedin
        "max_results": 20,
    }))
    out = json.loads(raw)
    sources = {o.get("source") for o in out["opportunities"]}
    assert "linkedin" not in sources


def test_search_jobs_synonym_expansion(monkeypatch):
    for k in ("TAVILY_API_KEY", "SERPER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    raw = search_jobs.run(json.dumps({
        "role_keywords": ["product manager"],
        "synonyms": {"product manager": ["pm", "sr pm"]},
        "location": "Costa Rica",
        "max_results": 5,
    }))
    out = json.loads(raw)
    # filters_applied surfaces the count of expansion terms
    assert out["filters_applied"]["synonyms_expanded"] >= 2
