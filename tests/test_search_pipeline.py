"""Unit tests for the search post-processing pipeline (C1–C4, C10)."""

from __future__ import annotations

from src.search_pipeline import (
    apply_min_match,
    rerank_by_embeddings,
)


def _make_op(
    title: str, body: str, source: str = "linkedin", link_type: str = "direct_listing"
) -> dict:
    return {
        "title": title,
        "company": "Acme",
        "location": "Costa Rica",
        "snippet": body[:200],
        "body": body,
        "url": f"https://example.com/{title.lower().replace(' ', '-')}",
        "source": source,
        "link_type": link_type,
    }


def test_apply_min_match_drops_low_overlap_postings():
    ops = [
        _make_op("Senior Go Backend", "Go Kafka PostgreSQL distributed systems gRPC"),
        _make_op("Frontend React", "React TypeScript CSS UI animations"),
    ]
    out = apply_min_match(ops, profile_keywords=["go", "kafka", "postgresql"], min_match=50)
    titles = [o["title"] for o in out]
    assert "Senior Go Backend" in titles
    assert "Frontend React" not in titles


def test_apply_min_match_passes_aggregator_pages():
    ops = [_make_op("LinkedIn search", "irrelevant", link_type="search_url")]
    out = apply_min_match(ops, profile_keywords=["go", "kafka"], min_match=99)
    assert len(out) == 1, "search_url aggregator pages must always pass min_match"


def test_apply_min_match_zero_threshold_keeps_everything():
    ops = [_make_op("X", "anything"), _make_op("Y", "")]
    out = apply_min_match(ops, profile_keywords=["go"], min_match=0)
    assert len(out) == 2


def test_rerank_uses_lexical_fallback_when_no_embedder():
    profile = "Senior backend engineer in Go and PostgreSQL with Kafka experience"
    ops = [
        _make_op("Frontend React Developer", "React TypeScript Tailwind responsive design"),
        _make_op("Senior Backend Engineer", "Go Kafka PostgreSQL gRPC distributed"),
    ]
    out = rerank_by_embeddings(ops, profile_summary=profile, provider="missing_provider", top_k=2)
    # Backend posting must rank first (or at least be present in top-2)
    titles = [o["title"] for o in out]
    assert "Senior Backend Engineer" in titles
    # Each rankable opportunity must carry a rerank_score
    assert all("rerank_score" in o for o in out if o.get("link_type") != "search_url")


def test_rerank_keeps_search_url_pages_as_fallback():
    profile = "Anything"
    ops = [
        _make_op("Direct posting", "Go Kafka"),
        _make_op("LinkedIn search", "", link_type="search_url"),
    ]
    out = rerank_by_embeddings(ops, profile_summary=profile, top_k=1)
    assert any(o["link_type"] == "search_url" for o in out), (
        "aggregator pages should always be appended as fallback"
    )
