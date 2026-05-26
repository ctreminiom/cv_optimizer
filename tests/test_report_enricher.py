"""Tests for src/report/enricher.py (Phase 3c extraction)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.report.enricher import (
    classify_match_with_opus,
    decision_helper_with_opus,
    posting_freshness,
    prescreen_with_haiku,
)

# ── posting_freshness ─────────────────────────────────────────────────────────


def test_posting_freshness_no_file_returns_dash() -> None:
    result = posting_freshness(Path("/nonexistent/file.md"))
    assert result == "—"


def test_posting_freshness_fresh_file(tmp_path) -> None:
    f = tmp_path / "job.md"
    f.write_text("Posted: 2 hours ago\n\nSome job description", encoding="utf-8")
    result = posting_freshness(f)
    assert "Fresh" in result or "Recent" in result or "🟢" in result


def test_posting_freshness_old_file(tmp_path) -> None:
    f = tmp_path / "job.md"
    f.write_text("Posted: 60 days ago\n\nSome job description", encoding="utf-8")
    result = posting_freshness(f)
    assert "🟠" in result or "Stale" in result or "old" in result


def test_posting_freshness_pdf_uses_mtime(tmp_path) -> None:
    f = tmp_path / "job.pdf"
    f.write_bytes(b"%PDF fake")
    result = posting_freshness(f)
    assert isinstance(result, str)
    assert result != ""


# ── decision_helper_with_opus ─────────────────────────────────────────────────


def test_decision_helper_falls_back_on_client_failure() -> None:
    report = {
        "job": {"title": "SWE", "company": "ACME"},
        "evaluations": [],
        "gap_analysis": {},
        "ats_report": {},
        "consolidated_feedback": {},
    }
    with patch("src.llm.client.get_default_client", side_effect=Exception("no key")):
        result = decision_helper_with_opus(report)
    assert isinstance(result, dict)
    assert "verdict" in result


def test_decision_helper_uses_injected_response() -> None:
    from tests.test_llm_client import _MockClient

    verdict_json = json.dumps(
        {
            "verdict": "✅ Apply — strong candidate",
            "reason": "Strong Go background matches the stack.",
            "pros": ["10 years Go experience"],
            "cons": ["Missing Kubernetes certification"],
        }
    )
    mock = _MockClient(response=verdict_json)

    report = {
        "job": {"title": "Backend Eng", "company": "X"},
        "evaluations": [
            {"agent_role": "HR", "strengths": ["Go"], "weaknesses": [], "red_flags": []}
        ],
        "gap_analysis": {"critical_gaps": [], "minor_gaps": []},
        "ats_report": {"missing_keywords": []},
        "consolidated_feedback": {"common_strengths": [], "common_weaknesses": []},
    }

    with patch("src.llm.client.get_default_client", return_value=mock):
        result = decision_helper_with_opus(report)

    assert result["verdict"] == "✅ Apply — strong candidate"
    assert len(result["pros"]) == 1


# ── classify_match_with_opus ──────────────────────────────────────────────────


def test_classify_match_falls_back_on_client_failure() -> None:
    evs = [{"agent_role": "HR", "strengths": ["Go"], "weaknesses": []}]
    with patch("src.llm.client.get_default_client", side_effect=Exception("no key")):
        result = classify_match_with_opus(evs, {}, {}, {})
    assert isinstance(result, list)


def test_classify_match_empty_evaluations_returns_empty() -> None:
    from tests.test_llm_client import _MockClient

    mock = _MockClient(response="[]")
    with patch("src.llm.client.get_default_client", return_value=mock):
        result = classify_match_with_opus([], {}, {}, {})
    assert result == []


# ── prescreen_with_haiku ──────────────────────────────────────────────────────


def test_prescreen_falls_open_on_client_failure(tmp_path) -> None:
    cv = tmp_path / "cv.md"
    job = tmp_path / "job.md"
    cv.write_text("Developer with 5 years Go", encoding="utf-8")
    job.write_text("Backend Engineer — Go, gRPC", encoding="utf-8")

    with patch("src.llm.client.get_default_client", side_effect=Exception("no key")):
        result = prescreen_with_haiku(cv, job)

    assert result["proceed"] is True
    assert "unavailable" in result["reason"].lower()


def test_prescreen_uses_injected_client(tmp_path) -> None:
    from tests.test_llm_client import _MockClient

    cv = tmp_path / "cv.md"
    job = tmp_path / "job.md"
    cv.write_text("Python developer, 5 years", encoding="utf-8")
    job.write_text("Python backend role, remote", encoding="utf-8")

    mock = _MockClient(response='{"verdict": "proceed", "reason": "Strong Python match."}')
    with patch("src.llm.client.get_default_client", return_value=mock):
        result = prescreen_with_haiku(cv, job)

    assert result["proceed"] is True
    assert "Python" in result["reason"]


def test_prescreen_skip_verdict(tmp_path) -> None:
    from tests.test_llm_client import _MockClient

    cv = tmp_path / "cv.md"
    job = tmp_path / "job.md"
    cv.write_text("Java developer", encoding="utf-8")
    job.write_text("Must speak French, Parisian office mandatory, C++ expert", encoding="utf-8")

    mock = _MockClient(response='{"verdict": "skip", "reason": "Language and location mismatch."}')
    with patch("src.llm.client.get_default_client", return_value=mock):
        result = prescreen_with_haiku(cv, job)

    assert result["proceed"] is False
    assert result["verdict"] == "skip"
