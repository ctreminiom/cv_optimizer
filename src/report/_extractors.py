"""Default task extractors — registered at import time.

This module encodes the task-name → report-key mapping that lived in
_augment_report_from_tasks. Importing this module registers the extractor;
src/report/__init__.py does that automatically.
"""

from __future__ import annotations

from typing import Any

from src.constants import (
    TASK_ATS_EVAL,
    TASK_COMPETITOR,
    TASK_CONSOLIDATE,
    TASK_COVER_LETTER,
    TASK_EXTRACT_VOICE,
    TASK_GAP_ANALYSIS,
    TASK_HIRING_EVAL,
    TASK_HR_EVAL,
    TASK_HUMANIZE_CV,
    TASK_HUMANIZE_RETRY,
    TASK_INTERVIEW_PREP,
    TASK_MIRRORING_CHECK,
    TASK_PARSE_CV,
    TASK_PARSE_JOB,
    TASK_REWRITE_CV,
    TASK_SECOND_OPINION,
    TASK_TECHNICAL_EVAL,
    TASK_VERIFICATION,
)
from src.report.builder import _coerce_value, register_extractor


@register_extractor
class _NamedTaskExtractor:
    """Resolves by task name first, then pydantic class, then description substr."""

    _task_to_key: dict[str, Any] = {
        TASK_PARSE_JOB: "job",
        TASK_PARSE_CV: "candidate_profile",
        TASK_EXTRACT_VOICE: "voice_signature",
        TASK_HR_EVAL: ("evaluations", "list_append"),
        TASK_HIRING_EVAL: ("evaluations", "list_append"),
        TASK_TECHNICAL_EVAL: ("evaluations", "list_append"),
        TASK_ATS_EVAL: "ats_report",
        TASK_GAP_ANALYSIS: "gap_analysis",
        TASK_SECOND_OPINION: "second_opinion",
        TASK_COMPETITOR: "competitor_profile",
        TASK_CONSOLIDATE: "consolidated_feedback",
        TASK_REWRITE_CV: "adapted_cv",
        TASK_HUMANIZE_CV: "authenticity_report",
        TASK_HUMANIZE_RETRY: "authenticity_report",
        TASK_MIRRORING_CHECK: "mirroring_report",
        TASK_VERIFICATION: "verification_report",
        TASK_INTERVIEW_PREP: "interview_questions",
        TASK_COVER_LETTER: "cover_letter",
    }

    _pydantic_class_to_key: dict[str, str] = {
        "JobPosting": "job",
        "CandidateProfile": "candidate_profile",
        "CompetitorProfile": "competitor_profile",
        "ATSReport": "ats_report",
        "GapAnalysis": "gap_analysis",
        "SecondOpinion": "second_opinion",
    }

    _substr_to_key: tuple[tuple[str, str], ...] = (
        ("parse_job", "job"),
        ("parse_cv", "candidate_profile"),
        ("competitor", "competitor_profile"),
    )

    def extract(self, task_out: Any) -> tuple[Any, Any] | None:
        name = (
            getattr(task_out, "name", "")
            or getattr(task_out, "task_name", "")
            or getattr(getattr(task_out, "task", None), "name", "")
            or ""
        )
        name = name.lower() if isinstance(name, str) else ""

        key: Any = self._task_to_key.get(name)

        if key is None:
            pydantic_obj = getattr(task_out, "pydantic", None)
            if pydantic_obj is not None:
                cls = type(pydantic_obj).__name__
                key = self._pydantic_class_to_key.get(cls)

        if key is None:
            desc = getattr(getattr(task_out, "task", None), "description", "") or ""
            hay = f"{name} {desc}".lower()
            for needle, candidate_key in self._substr_to_key:
                if needle in hay:
                    key = candidate_key
                    break

        if key is None:
            return None

        value = _coerce_value(task_out)
        if value is None:
            return None
        return key, value
