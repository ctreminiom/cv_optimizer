"""Unit tests for task guardrails (A2)."""

from __future__ import annotations

import json

from src.guardrails import (
    candidate_profile_completeness,
    consolidated_feedback_present,
    job_posting_completeness,
)


def test_job_posting_completeness_accepts_valid():
    ok, _ = job_posting_completeness(
        json.dumps(
            {
                "title": "Senior Backend Engineer",
                "requirements": [
                    {"text": "5+ years Go"},
                    {"text": "PostgreSQL"},
                    {"text": "Kafka"},
                ],
            }
        )
    )
    assert ok is True


def test_job_posting_completeness_rejects_empty_title():
    ok, msg = job_posting_completeness(
        json.dumps(
            {
                "title": "",
                "requirements": [1, 2, 3],
            }
        )
    )
    assert ok is False
    assert "title" in msg.lower()


def test_job_posting_completeness_rejects_too_few_requirements():
    ok, msg = job_posting_completeness(
        json.dumps(
            {
                "title": "Backend",
                "requirements": ["only one"],
            }
        )
    )
    assert ok is False
    assert "requirements" in msg.lower()


def test_job_posting_completeness_rejects_non_json():
    ok, msg = job_posting_completeness("this is not json")
    assert ok is False


def test_candidate_profile_completeness_accepts_valid():
    ok, _ = candidate_profile_completeness(
        json.dumps(
            {
                "work_experience": [{"title": "Engineer", "company": "X"}],
                "skills": ["Go", "Python"],
            }
        )
    )
    assert ok is True


def test_candidate_profile_completeness_rejects_empty_work():
    ok, msg = candidate_profile_completeness(
        json.dumps(
            {
                "work_experience": [],
                "skills": ["Go"],
            }
        )
    )
    assert ok is False
    assert "work_experience" in msg.lower()


def test_consolidated_feedback_present_rejects_empty_changes():
    ok, msg = consolidated_feedback_present(
        json.dumps(
            {
                "executive_summary": "A reasonably long summary that covers the basics of the candidate.",
                "prioritized_changes": [],
            }
        )
    )
    assert ok is False
    assert "prioritized_changes" in msg.lower()


def test_consolidated_feedback_present_rejects_short_summary():
    ok, msg = consolidated_feedback_present(
        json.dumps(
            {
                "executive_summary": "Too short.",
                "prioritized_changes": ["one", "two", "three"],
            }
        )
    )
    assert ok is False
    assert "summary" in msg.lower()
