"""Tests for src/pipeline/url_filters.py."""
from __future__ import annotations

from src.pipeline.url_filters import (
    content_matches_url_slug,
    is_linkedin_category_aggregator,
    is_location_relevant,
    is_login_walled,
    is_stale_listing,
    is_user_or_company_profile,
    normalize_source_from_url,
    summarize_extracted_content,
    url_slug_tokens,
)


def test_is_user_or_company_profile_catches_linkedin_in():
    assert is_user_or_company_profile({"url": "https://linkedin.com/in/jane-doe"}) is True
    assert is_user_or_company_profile({"url": "https://linkedin.com/company/acme"}) is True


def test_is_user_or_company_profile_passes_job_url():
    assert is_user_or_company_profile({"url": "https://linkedin.com/jobs/view/12345"}) is False


def test_is_linkedin_category_aggregator_catches_search_pages():
    assert is_linkedin_category_aggregator(
        "https://linkedin.com/jobs/project-manager-jobs-costa-rica") is True


def test_is_linkedin_category_aggregator_passes_search_endpoint():
    assert is_linkedin_category_aggregator(
        "https://linkedin.com/jobs/search?keywords=python") is False


def test_normalize_source_from_url():
    assert normalize_source_from_url("https://greenhouse.io/jobs/123") == "greenhouse"
    assert normalize_source_from_url("https://www.glassdoor.com/job/x") == "glassdoor"
    assert normalize_source_from_url("https://unknown.example/x") is None


def test_url_slug_tokens_skips_stopwords_and_numeric_ids():
    tokens = url_slug_tokens(
        "https://example.com/jobs/view/senior-go-engineer-at-acme-4260834487")
    assert "senior" in tokens
    assert "engineer" in tokens
    # Stopwords ("at", "view", "jobs") must be filtered out
    assert "at" not in tokens
    assert "view" not in tokens


def test_is_stale_listing_catches_year_ago():
    assert is_stale_listing("Posted 2 years ago") is True
    assert is_stale_listing("Posted 3 months ago") is False  # below 6-month threshold


def test_is_login_walled_short_content_is_walled():
    assert is_login_walled("") is True
    assert is_login_walled("short") is True


def test_is_login_walled_phrase_detection():
    walled = "Sign in to view this job " * 30  # long enough to clear length check
    assert is_login_walled(walled) is True


def test_is_location_relevant_costa_rica_terms():
    body = "We're hiring engineers based in San José, Costa Rica."
    assert is_location_relevant(body, "Costa Rica") is True


def test_is_location_relevant_remote_keyword():
    body = "Fully remote position open to candidates in LATAM. " * 5
    assert is_location_relevant(body, "Costa Rica") is True


def test_content_matches_url_slug_validates_slug_tokens():
    url = "https://example.com/jobs/senior-python-engineer-12345"
    matching_body = ("Senior Python Engineer\nWe're hiring a senior python engineer "
                     "to lead our backend team. The engineer will own service design.")
    assert content_matches_url_slug(matching_body, url) is True
    assert content_matches_url_slug("Unrelated content about anything else", url) is False


def test_summarize_extracted_content_trims_and_cleans():
    raw = ("Cookie banner here\n"
           "We use cookies on this site\n"
           "We're hiring a Senior Backend Engineer to build distributed payment "
           "systems handling millions of transactions per day. You'll partner with "
           "product and data teams. Strong Go and PostgreSQL experience required.")
    out = summarize_extracted_content(raw, max_chars=600)
    assert "Senior Backend Engineer" in out
    assert "cookie" not in out.lower()
