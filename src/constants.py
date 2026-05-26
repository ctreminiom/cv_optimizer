"""Shared string constants — task names and model ID defaults.

Centralising these prevents silent mismatches when task names change.
Reference these instead of writing literal strings in task_to_key dicts,
_TASK_VIS maps, or crew configurations.
"""

from __future__ import annotations

__all__ = [
    # Task names
    "TASK_PARSE_JOB",
    "TASK_PARSE_CV",
    "TASK_HR_EVAL",
    "TASK_HIRING_EVAL",
    "TASK_TECHNICAL_EVAL",
    "TASK_ATS_EVAL",
    "TASK_GAP_ANALYSIS",
    "TASK_SECOND_OPINION",
    "TASK_COMPETITOR",
    "TASK_CONSOLIDATE",
    "TASK_REWRITE_CV",
    "TASK_HUMANIZE_CV",
    "TASK_HUMANIZE_RETRY",
    "TASK_MIRRORING_CHECK",
    "TASK_VERIFICATION",
    "TASK_INTERVIEW_PREP",
    "TASK_COVER_LETTER",
    "TASK_EXTRACT_VOICE",
    # Model ID defaults
    "DEFAULT_MODEL_HAIKU",
    "DEFAULT_MODEL_SONNET",
]

# Task name constants — match config/tasks.yaml keys exactly
TASK_PARSE_JOB = "parse_job_task"
TASK_PARSE_CV = "parse_cv_task"
TASK_HR_EVAL = "hr_evaluation_task"
TASK_HIRING_EVAL = "hiring_manager_evaluation_task"
TASK_TECHNICAL_EVAL = "technical_evaluation_task"
TASK_ATS_EVAL = "ats_evaluation_task"
TASK_GAP_ANALYSIS = "gap_analysis_task"
TASK_SECOND_OPINION = "second_opinion_task"
TASK_COMPETITOR = "competitor_simulation_task"
TASK_CONSOLIDATE = "consolidate_feedback_task"
TASK_REWRITE_CV = "rewrite_cv_task"
TASK_HUMANIZE_CV = "humanize_cv_task"
TASK_HUMANIZE_RETRY = "humanize_retry_task"
TASK_MIRRORING_CHECK = "mirroring_check_task"
TASK_VERIFICATION = "verification_task"
TASK_INTERVIEW_PREP = "interview_prep_task"
TASK_COVER_LETTER = "cover_letter_task"
TASK_EXTRACT_VOICE = "extract_voice_task"

# Default model IDs — mirror Settings field defaults so both stay in sync
DEFAULT_MODEL_HAIKU = "claude-haiku-4-5-20251001"
DEFAULT_MODEL_SONNET = "claude-sonnet-4-6"
