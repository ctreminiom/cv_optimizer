"""Tests for src/pipeline/scoring.py."""

from __future__ import annotations

from src.pipeline.scoring import (
    VERDICT_TIERS,
    audit_quantification,
    audit_weak_words,
    build_pre_submission_checklist,
    compute_skill_alignment_matrix,
    decision_helper,
    effort_impact_quadrant,
    estimate_score_uplift,
    extract_strong_verbs_from_jd,
    match_by_category,
    qualitative_match_by_category,
    status_badge,
)


def test_compute_skill_alignment_full_match():
    job = {
        "requirements": [{"text": "5+ years Python", "priority": "must"}],
        "tech_stack": ["python"],
    }
    candidate = {"skills": ["Python", "Go"]}
    matrix = compute_skill_alignment_matrix(job, candidate)
    assert matrix[0]["status"] == "✅"


def test_compute_skill_alignment_missing():
    # The candidate has no Rust skill and nothing in the requirement text overlaps
    # with their skills, so the requirement is fully missing.
    job = {
        "requirements": [{"text": "Rust expertise required", "priority": "must"}],
        "tech_stack": [],
    }
    candidate = {"skills": ["Python"]}
    assert compute_skill_alignment_matrix(job, candidate)[0]["status"] == "❌"


def test_audit_quantification_flags_bullets_without_numbers():
    wx = [
        {
            "title": "Eng",
            "company": "X",
            "bullets": [
                "Led a team",  # no number → flagged
                "Shipped 5 features last quarter",  # has number → ok
            ],
        }
    ]
    flagged = audit_quantification(wx)
    assert len(flagged) == 1
    assert flagged[0]["bullet"] == "Led a team"


def test_audit_weak_words_catches_responsible_for():
    wx = [{"bullets": ["Responsible for the backend services"]}]
    out = audit_weak_words(wx)
    assert out and "responsible for" in out[0]["weak_phrases"]


def test_extract_strong_verbs_from_jd():
    job = {
        "responsibilities": [
            "Design and ship distributed systems",
            "Design and lead the engineering team",
            "Mentor junior engineers and ship features",
        ]
    }
    verbs = extract_strong_verbs_from_jd(job)
    assert isinstance(verbs, list)
    assert all(v[0].isupper() for v in verbs if v)


def test_estimate_score_uplift_projects_improvement():
    report = {
        "overall_match_score": 60,
        "consolidated_feedback": {
            "prioritized_changes": [
                {"impact": "high"},
                {"impact": "high"},
                {"impact": "medium"},
            ]
        },
    }
    out = estimate_score_uplift(report)
    assert out["current"] == 60
    assert out["projected"] >= 70
    assert out["high"] == 2
    assert out["medium"] == 1


def test_effort_impact_quadrant_buckets():
    report = {
        "consolidated_feedback": {
            "prioritized_changes": [
                {"impact": "high", "effort": "low"},
                {"impact": "low", "effort": "high"},
            ]
        }
    }
    grid = effort_impact_quadrant(report)
    assert len(grid["high_low"]) == 1  # quick wins
    assert len(grid["low_high"]) == 1
    assert len(grid["low_low"]) == 0


def test_match_by_category_uses_max_per_label():
    out = match_by_category(
        [
            {"agent_role": "HR Specialist", "fit_score": 70},
            {"agent_role": "HR Specialist", "fit_score": 80},
        ]
    )
    assert out["Cultural / Soft Skills"] == 80


def test_status_badge_strong_fit():
    emoji, label, _ = status_badge(
        {
            "gap_analysis": {"critical_gaps": []},
            "evaluations": [],
            "ats_report": {"missing_keywords": []},
        }
    )
    assert emoji == "🟢"
    assert "Strong" in label


def test_status_badge_major_mismatch():
    emoji, _, _ = status_badge(
        {
            "gap_analysis": {"critical_gaps": ["a", "b", "c", "d", "e"]},
            "evaluations": [],
            "ats_report": {},
        }
    )
    assert emoji == "🔴"


def test_decision_helper_apply_strong():
    out = decision_helper(
        {
            "overall_match_score": 80,
            "gap_analysis": {"critical_gaps": []},
            "evaluations": [],
            "job": {"modality": "remote", "salary_range": "$90,000 USD"},
        }
    )
    assert out["verdict"] == VERDICT_TIERS[0]
    assert "No critical gaps" in out["pros"]


def test_decision_helper_skip_major_mismatch():
    out = decision_helper(
        {
            "gap_analysis": {"critical_gaps": ["a"] * 5},
            "evaluations": [{"red_flags": ["x", "y", "z"]}],
            "job": {"modality": "on_site"},
        }
    )
    assert out["verdict"] == VERDICT_TIERS[3]


def test_build_pre_submission_checklist_dedupes_paraphrases():
    # Two phrasings sharing ≥4 significant tokens should collapse into one.
    report = {
        "evaluations": [
            {
                "red_flags": [
                    "Candidate lacks SAFe certification and Agile methodology experience",
                    "Missing SAFe certification and Agile methodology experience credential",
                ]
            }
        ],
        "gap_analysis": {"critical_gaps": []},
        "consolidated_feedback": {"prioritized_changes": []},
        "ats_report": {"missing_keywords": [], "format_issues": []},
    }
    out = build_pre_submission_checklist(report)
    assert len(out) == 1


def test_build_pre_submission_checklist_keeps_distinct_items():
    # Items with no significant token overlap must be kept separately.
    report = {
        "evaluations": [
            {
                "red_flags": [
                    "Missing SAFe certification",
                    "Insufficient incident-response experience",
                ]
            }
        ],
        "gap_analysis": {"critical_gaps": []},
        "consolidated_feedback": {"prioritized_changes": []},
        "ats_report": {"missing_keywords": [], "format_issues": []},
    }
    out = build_pre_submission_checklist(report)
    assert len(out) == 2


def test_qualitative_match_by_category_buckets_evaluations():
    out = qualitative_match_by_category(
        [
            {
                "agent_role": "HR Specialist",
                "strengths": ["a", "b", "c"],
                "weaknesses": [],
                "red_flags": [],
            },
            {
                "agent_role": "Technical Specialist",
                "strengths": [],
                "weaknesses": ["x"],
                "red_flags": ["y"],
            },
        ]
    )
    assert len(out) == 2
    bands = {row["band"] for row in out}
    assert "🟢 Strong" in bands or "🟡 Solid" in bands
    assert "🔴 Weak" in bands
