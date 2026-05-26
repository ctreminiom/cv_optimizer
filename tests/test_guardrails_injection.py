"""Tests for guardrail DIP fix — injectable quality checkers."""
from __future__ import annotations

import json

from src.guardrails import adapted_cv_no_fabrication


def _make_adapted_cv(bullets: list[str]) -> dict:
    return {
        "job_title": "Engineer",
        "company": "Acme",
        "sections": [{"name": "Experience", "bullets": bullets}],
    }


def test_adapted_cv_passes_with_clean_mock() -> None:
    clean_smell = lambda _: json.dumps({"ai_smell_score": 10, "issues": []})
    clean_critique = lambda _: json.dumps({"issues": []})
    data = _make_adapted_cv(["Reduced API latency by 40% through caching."])
    ok, _ = adapted_cv_no_fabrication(data, smell_detector=clean_smell, self_critique_fn=clean_critique)
    assert ok is True


def test_adapted_cv_fails_on_high_ai_smell() -> None:
    smelly = lambda _: json.dumps({"ai_smell_score": 75, "issues": ["buzzword overuse"]})
    clean_critique = lambda _: json.dumps({"issues": []})
    data = _make_adapted_cv(["Leveraged synergies to spearhead innovative initiatives."])
    ok, msg = adapted_cv_no_fabrication(data, smell_detector=smelly, self_critique_fn=clean_critique)
    assert ok is False
    assert "ai_smell_score=75" in msg


def test_adapted_cv_fails_on_many_critique_flags() -> None:
    clean_smell = lambda _: json.dumps({"ai_smell_score": 5, "issues": []})
    flaggy = lambda _: json.dumps({"issues": ["passive phrasing"]})
    bullets = [
        "Was responsible for the backend.",
        "Helped with database migrations.",
        "Involved in various projects.",
        "Worked on infrastructure.",
        "Assisted the team with deployments.",
    ]
    data = _make_adapted_cv(bullets)
    ok, msg = adapted_cv_no_fabrication(data, smell_detector=clean_smell, self_critique_fn=flaggy)
    assert ok is False
    assert "3+" in msg


def test_adapted_cv_empty_sections_fails() -> None:
    clean_smell = lambda _: json.dumps({"ai_smell_score": 0, "issues": []})
    clean_critique = lambda _: json.dumps({"issues": []})
    data = {"job_title": "Engineer", "company": "Acme", "sections": []}
    ok, msg = adapted_cv_no_fabrication(data, smell_detector=clean_smell, self_critique_fn=clean_critique)
    assert ok is False
    assert "no bullets" in msg
