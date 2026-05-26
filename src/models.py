"""
models.py — Pydantic schemas for CV Optimizer v2.

v2 additions:
  • Confidence on evaluations (#11)
  • Self-critique on bullets (#5)
  • Salary benchmark + comparable openings (#9)
  • Competitor simulation (#17)
  • Job search results (search subcommand)
  • Eval set entries (#7)
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = [
    "JobRequirement",
    "JobPosting",
    "WorkExperience",
    "Education",
    "CandidateProfile",
    "VoiceSignature",
    "AgentEvaluation",
    "GapAnalysis",
    "ATSReport",
    "SecondOpinion",
    "CompetitorProfile",
    "PrioritizedChange",
    "ConsolidatedFeedback",
    "RewrittenBullet",
    "RewrittenSection",
    "AdaptedCV",
    "AuthenticityReport",
    "MirroringReport",
    "VerificationReport",
    "JobOpportunity",
    "JobSearchResult",
    "InterviewQuestion",
    "CoverLetter",
    "JobReport",
    "RunSummary",
    "EvalExample",
    "EvalRunResult",
    "EvalSummary",
]


# ─── Job posting ──────────────────────────────────────────────────────────

class JobRequirement(BaseModel):
    text: str
    category: Literal["technical", "soft", "experience", "education", "language", "other"]
    priority: Literal["must_have", "nice_to_have"]


class JobPosting(BaseModel):
    source_file: str
    title: str
    company: str
    location: str | None = None
    modality: Literal["remote", "hybrid", "on_site", "unknown"] | None = "unknown"
    seniority: Literal["junior", "mid", "senior", "lead", "principal", "unknown"] | None = "unknown"
    salary_range: str | None = None

    role_type: str
    tech_stack: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[JobRequirement] = Field(default_factory=list)
    ats_keywords: list[str] = Field(default_factory=list)
    cultural_signals: list[str] = Field(default_factory=list)


# ─── CV ───────────────────────────────────────────────────────────────────

class WorkExperience(BaseModel):
    company: str
    title: str
    start_date: str
    end_date: str = "Present"
    location: str | None = None
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    degree: str
    field: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class CandidateProfile(BaseModel):
    source_file: str
    full_name: str
    headline: str | None = None
    summary: str | None = None
    contact: dict[str, str] = Field(default_factory=dict)

    work_experience: list[WorkExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class VoiceSignature(BaseModel):
    formality_level: Literal["casual", "balanced", "formal"] = "balanced"
    typical_bullet_starters: list[str] = Field(default_factory=list)
    avg_bullet_word_count: int = 20
    signature_phrases: list[str] = Field(default_factory=list)
    quantification_style: Literal["heavy_metrics", "selective", "qualitative"] = "selective"
    representative_bullets: list[str] = Field(
        default_factory=list,
        description="5-6 high-quality original bullets used as few-shot exemplars (#4)",
    )


# ─── Evaluation ───────────────────────────────────────────────────────────

class AgentEvaluation(BaseModel):
    agent_role: str
    fit_score: int = Field(ge=0, le=100, default=50)
    confidence: int = Field(ge=0, le=100, default=70)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    notes: str | None = None
    uncertain_items: list[str] = Field(default_factory=list)


class GapAnalysis(BaseModel):
    critical_gaps: list[str] = Field(default_factory=list)
    minor_gaps: list[str] = Field(default_factory=list)
    framing_opportunities: list[str] = Field(default_factory=list)


class ATSReport(BaseModel):
    keyword_match_pct: float = Field(ge=0, le=100, default=0.0)
    missing_keywords: list[str] = Field(default_factory=list)
    overused_keywords: list[str] = Field(default_factory=list)
    format_issues: list[str] = Field(default_factory=list)
    keyword_suggestions: list[dict[str, str]] = Field(default_factory=list)


class SecondOpinion(BaseModel):
    triggered: bool = False
    reason: str = ""
    final_score: int = Field(ge=0, le=100, default=0)
    rationale: str = ""


class CompetitorProfile(BaseModel):
    summary: str = ""
    bullets: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    candidate_advantages: list[str] = Field(default_factory=list)


# ─── Synthesis ────────────────────────────────────────────────────────────

class PrioritizedChange(BaseModel):
    target_section: str = ""
    change_type: Literal["add", "remove", "rewrite", "reorder", "reframe"] = "rewrite"
    description: str = ""
    impact: Literal["low", "medium", "high"] = "medium"
    effort: Literal["low", "medium", "high"] = "medium"
    source_agents: list[str] = Field(default_factory=list)


class ConsolidatedFeedback(BaseModel):
    overall_match_score: int = Field(ge=0, le=100, default=50)
    overall_confidence: int = Field(ge=0, le=100, default=70)
    executive_summary: str = ""
    prioritized_changes: list[PrioritizedChange] = Field(default_factory=list)
    contradictions_resolved: list[str] = Field(default_factory=list)


# ─── Rewriting ────────────────────────────────────────────────────────────

class RewrittenBullet(BaseModel):
    original: str
    rewritten: str
    reasoning: str
    fabrication_check: Literal["safe", "needs_review"] = "safe"
    self_critique: str | None = None


class RewrittenSection(BaseModel):
    name: str
    bullets: List[RewrittenBullet] = Field(default_factory=list)
    summary_text: str | None = None


class AdaptedCV(BaseModel):
    job_title: str
    company: str
    target_role_type: str
    summary: str
    sections: list[RewrittenSection] = Field(default_factory=list)
    keywords_injected: list[str] = Field(default_factory=list)
    word_count: int = 0


# ─── Quality gates ────────────────────────────────────────────────────────

class AuthenticityReport(BaseModel):
    ai_smell_score: int = Field(ge=0, le=100, default=0)
    detected_buzzwords: list[str] = Field(default_factory=list)
    sentence_uniformity_issue: bool = False
    metric_credibility_issues: list[str] = Field(default_factory=list)
    suggested_revisions: list[str] = Field(default_factory=list)
    passes: bool = True
    iteration: int = 1


class MirroringReport(BaseModel):
    similarity_score: float = Field(ge=0, le=1, default=0.0)
    mirrored_phrases: list[str] = Field(default_factory=list)
    passes: bool = True
    iteration: int = 1


class VerificationReport(BaseModel):
    fabrications_found: list[dict[str, str]] = Field(default_factory=list)
    altered_facts: list[dict[str, str]] = Field(default_factory=list)
    exaggeration_risks: list[str] = Field(default_factory=list)
    passes: bool
    iteration: int = 1


# ─── Search (new subcommand) ──────────────────────────────────────────────

class JobOpportunity(BaseModel):
    """A single job opening with an absolute URL for the user to open."""
    title: str
    company: str
    location: str
    modality: str | None = None
    posted_date: str | None = None
    salary_hint: str | None = None
    snippet: str = Field(default="", description="short excerpt from the posting")
    url: str = Field(description="absolute URL to view/download the full posting")
    apply_url: str | None = Field(None, description="direct application URL if different from listing")
    source: str = Field(description="job board: linkedin, indeed, glassdoor, wellfound, remoteok, ...")
    match_score: int = Field(ge=0, le=100, default=0)
    why_relevant: str | None = None
    requirements_summary: list[str] = Field(default_factory=list, description="key requirements from the posting")
    tech_stack: list[str] = Field(default_factory=list, description="technologies mentioned")
    benefits: str | None = None
    contract_type: str | None = None
    experience_years: str | None = None
    application_deadline: str | None = None
    job_id: str | None = None


class JobSearchResult(BaseModel):
    cv_source: str = ""
    candidate_name: str | None = None
    candidate_headline: str | None = None
    location_filter: str = ""
    role_keywords: list[str] = Field(default_factory=list)
    seniority_filter: str | None = None
    modality_filter: str | None = None
    keywords_filter: list[str] = Field(default_factory=list)
    total_found: int = 0
    opportunities: list[JobOpportunity] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    search_queries_used: list[str] = Field(default_factory=list)
    search_timestamp: str = ""
    reports_dir: str | None = None


# ─── Final job report ─────────────────────────────────────────────────────

class InterviewQuestion(BaseModel):
    question: str
    reasoning: str
    suggested_angle: str


class CoverLetter(BaseModel):
    body: str = ""
    word_count: int = 0
    tone: str = "professional"


class JobReport(BaseModel):
    job: JobPosting | None = None
    candidate_profile: CandidateProfile | None = None
    overall_match_score: int = Field(ge=0, le=100, default=0)
    overall_confidence: int = Field(ge=0, le=100, default=70)
    executive_summary: str = ""

    evaluations: list[AgentEvaluation] = Field(default_factory=list)
    second_opinion: SecondOpinion | None = None
    gap_analysis: GapAnalysis | None = None
    ats_report: ATSReport | None = None
    consolidated_feedback: ConsolidatedFeedback | None = None

    adapted_cv: AdaptedCV | None = None
    authenticity_report: AuthenticityReport | None = None
    mirroring_report: MirroringReport | None = None
    verification_report: VerificationReport | None = None

    interview_questions: list[InterviewQuestion] = Field(default_factory=list)
    cover_letter: CoverLetter | None = None
    competitor_profile: CompetitorProfile | None = None

    output_files: dict[str, str] = Field(default_factory=dict)
    fingerprint: str | None = None
    cached: bool = False


class RunSummary(BaseModel):
    cv_master: str
    total_jobs_processed: int
    jobs_succeeded: int
    jobs_failed: int
    jobs_skipped_cached: int = 0
    reports: list[JobReport] = Field(default_factory=list)
    failed_jobs: list[dict[str, str]] = Field(default_factory=list)
    total_cost_estimate_usd: float | None = None
    elapsed_seconds: float | None = None


# ─── Eval harness (#7) ────────────────────────────────────────────────────

class EvalExample(BaseModel):
    name: str
    cv_path: str
    job_path: str
    expected_match_score_min: int = Field(ge=0, le=100)
    expected_match_score_max: int = Field(ge=0, le=100)
    must_include_keywords: list[str] = Field(default_factory=list)
    must_avoid_phrases: list[str] = Field(default_factory=list)
    notes: str | None = None


class EvalRunResult(BaseModel):
    example_name: str
    passed: bool
    actual_match_score: int
    issues: list[str] = Field(default_factory=list)
    elapsed_seconds: float


class EvalSummary(BaseModel):
    total_examples: int
    passed: int
    failed: int
    pass_rate: float
    results: list[EvalRunResult]
    elapsed_seconds: float
