"""AI quality-check tools for CV content.

detect_ai_smell      — flags generic AI-sounding language
detect_mirroring     — measures JD phrase overlap in the CV
self_critique_bullet — pre-submission self-audit for a single bullet
"""

from __future__ import annotations

import json
import re
from collections import Counter

from crewai.tools import tool

__all__ = ["detect_ai_smell", "detect_mirroring", "self_critique_bullet"]


_AI_BUZZWORDS = {
    "results-driven",
    "results-oriented",
    "dynamic professional",
    "passionate",
    "passionate team player",
    "passionate about",
    "proven track record",
    "synergy",
    "synergies",
    "leverage",
    "leveraging",
    "spearheaded",
    "innovative solutions",
    "team mindset",
    "highly motivated",
    "detail-oriented",
    "go-getter",
    "self-starter",
    "best-in-class",
    "world-class",
    "cutting-edge",
    "thought leader",
    "value-add",
    "deliverables",
    "stakeholders",
    "actionable insights",
    "transformative",
    "robust solutions",
    "seamless integration",
    "ecosystem",
    "paradigm shift",
    "game-changer",
    "mission-critical",
    "strategic vision",
    "forward-thinking",
}


@tool("detect_ai_smell")
def detect_ai_smell(text_json: str) -> str:
    """
    Detects AI-generated patterns: buzzwords, uniform sentence starters,
    metrics without methodology context. Used by Authenticity Agent.
    """
    try:
        data = json.loads(text_json)
        text = data.get("text", "")
    except Exception as e:
        return json.dumps({"error": f"invalid input: {e}"})

    text_lower = text.lower()
    detected_buzzwords = sorted({bw for bw in _AI_BUZZWORDS if bw in text_lower})

    bullets = [
        ln.strip().lstrip("•-*").strip()
        for ln in text.splitlines()
        if ln.strip().startswith(("•", "-", "*")) or re.match(r"^\s+[A-Z]", ln)
    ]
    starters = [b.split()[0].lower() for b in bullets if b.split()]
    most_common_starter = Counter(starters).most_common(1)
    uniformity_issue = (
        len(bullets) >= 5
        and most_common_starter
        and most_common_starter[0][1] / len(starters) > 0.45
    )

    metric_credibility_issues: list[str] = []
    for m in re.finditer(r"(\b\w+(?:\s+\w+){0,3})\s*\b\d{1,3}(?:\.\d+)?%", text):
        prefix = m.group(1).lower()
        if not any(
            w in prefix
            for w in [
                "by",
                "through",
                "via",
                "using",
                "after",
                "from",
                "with",
                "improved",
                "reduced",
                "increased",
            ]
        ):
            metric_credibility_issues.append(m.group(0))

    score = (
        min(len(detected_buzzwords) * 8, 50)
        + (25 if uniformity_issue else 0)
        + min(len(metric_credibility_issues) * 5, 25)
    )
    score = min(score, 100)

    suggested: list[str] = []
    if detected_buzzwords:
        suggested.append(
            f"Replace generic buzzwords ({', '.join(detected_buzzwords[:5])}) "
            "with specific descriptions."
        )
    if uniformity_issue:
        suggested.append("Vary bullet starters — too many begin the same way.")
    if metric_credibility_issues:
        suggested.append(f"Add methodology context to metrics ({metric_credibility_issues[0]}).")

    return json.dumps(
        {
            "ai_smell_score": score,
            "detected_buzzwords": detected_buzzwords,
            "sentence_uniformity_issue": uniformity_issue,
            "metric_credibility_issues": metric_credibility_issues[:10],
            "suggested_revisions": suggested,
            "passes": score < 35,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — Mirroring detector
# ─────────────────────────────────────────────────────────────────────────────
@tool("detect_mirroring")
def detect_mirroring(input_json: str) -> str:
    """
    Detects when adapted CV mirrors the job posting too closely.
    Returns similarity score and list of mirrored phrases.
    """
    try:
        data = json.loads(input_json)
        job_text = data.get("job_text", "").lower()
        cv_text = data.get("cv_text", "").lower()
    except Exception as e:
        return json.dumps({"error": f"invalid input: {e}"})

    job_words = job_text.split()
    cv_text_clean = re.sub(r"\s+", " ", cv_text)

    mirrored_phrases: list[str] = []
    n = 6
    seen: set = set()
    for i in range(len(job_words) - n + 1):
        phrase = " ".join(job_words[i : i + n])
        if phrase in seen:
            continue
        seen.add(phrase)
        if phrase in cv_text_clean and len(phrase.split()) >= n:
            mirrored_phrases.append(phrase)
    mirrored_phrases = sorted(set(mirrored_phrases))[:15]
    similarity = min(len(mirrored_phrases) / 10, 1.0)

    return json.dumps(
        {
            "similarity_score": similarity,
            "mirrored_phrases": mirrored_phrases,
            "passes": similarity < 0.3,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — Self-critique helper (#5)
# ─────────────────────────────────────────────────────────────────────────────
@tool("self_critique_bullet")
def self_critique_bullet(input_json: str) -> str:
    """
    Heuristic self-critique on a rewritten bullet. Flags any claim NOT
    supported by the original. Used by the Rewriter as a cheap first
    pass before the Verification Agent.
    """
    try:
        data = json.loads(input_json)
        original = data.get("original", "").lower()
        rewritten = data.get("rewritten", "").lower()
    except Exception as e:
        return json.dumps({"error": f"invalid input: {e}"})

    issues: list[str] = []

    # Check facts that should be present in original if claimed in rewritten
    rew_numbers = set(
        re.findall(r"\b\d{1,3}(?:\.\d+)?%|\b\d+\s*(?:engineers|services|teams|years)", rewritten)
    )
    orig_numbers = set(
        re.findall(r"\b\d{1,3}(?:\.\d+)?%|\b\d+\s*(?:engineers|services|teams|years)", original)
    )
    for n in rew_numbers - orig_numbers:
        issues.append(f"unsupported number: {n}")

    # Stronger verb in rewritten than original?
    weak_strong = {
        "led": ["collaborated", "contributed", "helped"],
        "owned": ["worked on", "supported"],
        "drove": ["assisted", "supported"],
    }
    for strong, weaks in weak_strong.items():
        if strong in rewritten and any(w in original for w in weaks):
            if strong not in original:
                issues.append(
                    f"verb escalation: original was '{[w for w in weaks if w in original][0]}', "
                    f"rewritten claims '{strong}'"
                )

    return json.dumps(
        {
            "issues": issues,
            "passes": len(issues) == 0,
        }
    )
