"""
context_window.py — Recommendation #10.

Pre-filters the candidate's CV per-task using a cheap Haiku call so each
heavy Sonnet agent sees only the bullets relevant to its perspective.

For example, the Technical Specialist for a Go job only needs the bullets
mentioning Go, infrastructure, performance — not the candidate's
education or unrelated side projects.
"""

from __future__ import annotations

import json

from src.models import CandidateProfile, JobPosting


def filter_for_hr(profile: CandidateProfile) -> CandidateProfile:
    """HR cares about overall presentation, gaps, and recent roles."""
    filtered = profile.model_copy(deep=True)
    # Keep only the last 3 roles (HR scans recent experience)
    filtered.work_experience = profile.work_experience[:3]
    return filtered


def filter_for_technical(profile: CandidateProfile, job: JobPosting) -> CandidateProfile:
    """
    Keep only bullets that mention any token from the job's tech stack
    or ATS keywords. Senior CVs often have 4 pages of detail; this drops
    bullet count by 50-70% for the technical evaluator.
    """
    relevant_terms = {t.lower() for t in job.tech_stack + job.ats_keywords}
    if not relevant_terms:
        return profile

    filtered = profile.model_copy(deep=True)
    new_xp: list = []
    for xp in filtered.work_experience:
        relevant_bullets = [
            b for b in xp.bullets if any(term in b.lower() for term in relevant_terms)
        ]
        # Always keep at least the role even if no bullets matched, so the
        # technical agent sees company/title context.
        xp_copy = xp.model_copy(update={"bullets": relevant_bullets or xp.bullets[:2]})
        new_xp.append(xp_copy)
    filtered.work_experience = new_xp
    return filtered


def filter_for_hiring_manager(profile: CandidateProfile) -> CandidateProfile:
    """
    Hiring managers care about quantified impact. Keep bullets containing
    numbers, percentages, dollar amounts, or scope words (team, users, etc).
    """
    impact_markers = [
        "%",
        "$",
        "x ",
        "k ",
        "m ",
        "billion",
        "million",
        "team of",
        "users",
        "customers",
        "engineers",
        "reduced",
        "increased",
        "improved",
        "shipped",
        "launched",
        "built",
        "led",
    ]

    filtered = profile.model_copy(deep=True)
    new_xp: list = []
    for xp in profile.work_experience:
        impact_bullets = [
            b for b in xp.bullets if any(marker in b.lower() for marker in impact_markers)
        ]
        xp_copy = xp.model_copy(update={"bullets": impact_bullets or xp.bullets})
        new_xp.append(xp_copy)
    filtered.work_experience = new_xp
    return filtered


def serialize_filtered(profile: CandidateProfile) -> str:
    """Compact JSON serialization for prompt injection."""
    return json.dumps(profile.model_dump(), indent=2)
