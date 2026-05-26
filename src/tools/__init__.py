"""Backwards-compatible re-export of all CrewAI tools.

All existing `from src.tools import X` imports continue to work unchanged.
New code should import directly from the sub-module (e.g., src.tools.job_parser).
"""
from __future__ import annotations

from src.tools.job_parser import parse_job_pdf
from src.tools.cv_parser import parse_cv, parse_cv_docx
from src.tools.voice import extract_voice_signature
from src.tools.keywords import compute_keyword_match, compute_cv_diff
from src.tools.quality import detect_ai_smell, detect_mirroring, self_critique_bullet
from src.tools.output import generate_docx_output, write_job_report
from src.tools.knowledge import load_domain_knowledge_base
from src.tools.search import search_jobs

__all__ = [
    "parse_job_pdf",
    "parse_cv",
    "parse_cv_docx",
    "extract_voice_signature",
    "compute_keyword_match",
    "compute_cv_diff",
    "detect_ai_smell",
    "detect_mirroring",
    "self_critique_bullet",
    "generate_docx_output",
    "write_job_report",
    "load_domain_knowledge_base",
    "search_jobs",
]
