"""Keyword matching and CV diff tools."""

from __future__ import annotations

import json
import re
from collections import Counter

from crewai.tools import tool

__all__ = ["compute_keyword_match", "compute_cv_diff"]


_STOPWORDS = set(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "for",
        "to",
        "in",
        "on",
        "at",
        "by",
        "from",
        "with",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "their",
        "our",
        "your",
        "we",
        "you",
        "they",
        "i",
        "me",
        "my",
        "so",
        "if",
        "then",
    ]
)


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = re.findall(r"[a-z][a-z0-9+#./-]*", text)
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


@tool("compute_keyword_match")
def compute_keyword_match(input_json: str) -> str:
    """
    ATS-style keyword match between job and CV. Used in multi-pass mode
    by the Rewriter (#13) — call after each section rewrite to track
    score progression.
    Input: {"job_text", "cv_text", "ats_keywords"}
    """
    try:
        data = json.loads(input_json)
        job_text = data.get("job_text", "")
        cv_text = data.get("cv_text", "")
        ats_keywords = [k.lower() for k in data.get("ats_keywords", [])]
    except Exception as e:
        return json.dumps({"error": f"invalid input: {e}"})

    cv_tokens = _tokenize(cv_text)
    cv_token_set = set(cv_tokens)
    cv_token_count = Counter(cv_tokens)

    if not ats_keywords:
        job_tokens = _tokenize(job_text)
        ats_keywords = [w for w, _ in Counter(job_tokens).most_common(20)]

    matched = [k for k in ats_keywords if k in cv_token_set]
    missing = [k for k in ats_keywords if k not in cv_token_set]
    match_pct = round((len(matched) / max(len(ats_keywords), 1)) * 100, 1)
    overused = [k for k, c in cv_token_count.items() if c > 5 and k in ats_keywords]
    top_cv_keywords = [w for w, _ in cv_token_count.most_common(15)]

    return json.dumps(
        {
            "match_pct": match_pct,
            "matched_keywords": matched,
            "missing_keywords": missing,
            "overused_keywords": overused,
            "top_cv_keywords": top_cv_keywords,
            "total_ats_keywords": len(ats_keywords),
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — CV diff / fabrication detector
# ─────────────────────────────────────────────────────────────────────────────
@tool("compute_cv_diff")
def compute_cv_diff(input_json: str) -> str:
    """
    Compares original CV text vs adapted CV text. Detects fabricated
    facts (percentages, dollar amounts, year ranges, team sizes) and
    verb escalation (collaborated → led).
    """
    try:
        data = json.loads(input_json)
        original = data.get("original_text", "")
        adapted = data.get("adapted_text", "")
    except Exception as e:
        return json.dumps({"error": f"invalid input: {e}"})

    fact_patterns = {
        "percentages": r"\b\d{1,3}(?:\.\d+)?%",
        "dollar_amounts": r"\$\s?\d[\d,]*(?:\.\d+)?[KkMmBb]?",
        "year_ranges": r"\b(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|[Pp]resent)",
        "team_sizes": r"\bteam of \d+|\b\d+\s*(?:engineers|developers|people|reports)",
        "duration": r"\b\d+\s*(?:years?|months?)\b",
    }

    fabrications: list[dict[str, str]] = []
    for name, pattern in fact_patterns.items():
        original_facts = set(re.findall(pattern, original, flags=re.IGNORECASE))
        adapted_facts = set(re.findall(pattern, adapted, flags=re.IGNORECASE))
        for f in adapted_facts - original_facts:
            fabrications.append({"category": name, "value": f, "appears_in": "adapted_only"})

    escalation_pairs = [
        ("collaborated", "led"),
        ("collaborated", "spearheaded"),
        ("contributed", "led"),
        ("helped", "led"),
        ("supported", "drove"),
        ("worked on", "owned"),
        ("assisted", "managed"),
    ]
    exaggeration_risks: list[str] = []
    for weak, strong in escalation_pairs:
        if weak in original.lower() and strong in adapted.lower() and weak not in adapted.lower():
            exaggeration_risks.append(f"original used '{weak}' — adapted uses '{strong}' (verify)")

    return json.dumps(
        {
            "fabrications_found": fabrications,
            "altered_facts": [],
            "exaggeration_risks": exaggeration_risks,
            "passes": len(fabrications) == 0 and len(exaggeration_risks) == 0,
        }
    )
