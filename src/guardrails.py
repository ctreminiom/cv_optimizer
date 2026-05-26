"""Task-output validators used as CrewAI task `guardrail` callables.

A guardrail returns `(True, value)` to accept the output or `(False, error)`
to ask the agent to retry. Errors are surfaced verbatim in the retry prompt,
so phrase them as actionable instructions.
"""

import json
import re
from collections.abc import Callable
from typing import Any

__all__ = [
    "job_posting_completeness",
    "candidate_profile_completeness",
    "consolidated_feedback_present",
    "adapted_cv_no_fabrication",
    "mirroring_under_threshold",
]

Result = tuple[bool, Any]

# Matches a fenced code block, optionally tagged ```json. Agents frequently
# wrap structured output this way even when asked for raw JSON.
_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _loads_lenient(payload: str) -> Any | None:
    """Parse JSON that may be fenced or surrounded by prose."""
    candidates = [payload]

    fence = _FENCE_RE.match(payload.strip())
    if fence:
        candidates.append(fence.group(1))

    # Fallback: slice from the first opening bracket to its matching close.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = payload.find(opener)
        end = payload.rfind(closer)
        if start != -1 and end > start:
            candidates.append(payload[start : end + 1])

    for text in candidates:
        try:
            return json.loads(text)
        except Exception:
            continue
    return None


def _as_dict(raw: Any) -> Any | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return raw
    payload = raw if isinstance(raw, str) else getattr(raw, "raw", None)
    if not isinstance(payload, str):
        return None
    return _loads_lenient(payload)


def job_posting_completeness(raw: Any) -> Result:
    data = _as_dict(raw)
    if not isinstance(data, dict):
        return False, "Output is not a JSON object matching JobPosting."
    if not (data.get("title") or "").strip():
        return False, "JobPosting.title is empty. Re-read the posting and extract the job title."
    requirements = data.get("requirements") or []
    if not isinstance(requirements, list) or len(requirements) < 2:
        return False, (
            "JobPosting.requirements has fewer than 2 entries. "
            "Most postings have at least 3 explicit requirements; "
            "re-read and extract them."
        )
    return True, raw


def candidate_profile_completeness(raw: Any) -> Result:
    data = _as_dict(raw)
    if not isinstance(data, dict):
        return False, "Output is not a JSON object matching CandidateProfile."
    work = data.get("work_experience") or []
    if not isinstance(work, list) or not work:
        return False, (
            "CandidateProfile.work_experience is empty. "
            "Re-read the CV and extract at least the most recent role."
        )
    skills = data.get("skills") or []
    if not isinstance(skills, list) or not skills:
        return False, (
            "CandidateProfile.skills is empty. "
            "Extract the skills list verbatim from the CV's Skills section."
        )
    return True, raw


def consolidated_feedback_present(raw: Any) -> Result:
    data = _as_dict(raw)
    if not isinstance(data, dict):
        return False, "Output is not a JSON object matching ConsolidatedFeedback."
    changes = data.get("prioritized_changes") or []
    if not isinstance(changes, list) or not changes:
        return False, (
            "ConsolidatedFeedback.prioritized_changes is empty — "
            "list at least 3 actionable changes."
        )
    summary = (data.get("executive_summary") or "").strip()
    if len(summary) < 50:
        return False, (
            "ConsolidatedFeedback.executive_summary is too short (<50 chars). Write 3-5 sentences."
        )
    return True, raw


SmellDetectorFn = Callable[[str], str]
SelfCritiqueFn = Callable[[str], str]


def adapted_cv_no_fabrication(
    raw: Any,
    *,
    smell_detector: SmellDetectorFn | None = None,
    self_critique_fn: SelfCritiqueFn | None = None,
) -> Result:
    """Rewriter guardrail. Reuses the AI-smell and self-critique tools.

    Args:
        smell_detector: Callable accepting text_json, returning JSON string.
            Defaults to detect_ai_smell.run.
        self_critique_fn: Callable accepting bullet_json, returning JSON string.
            Defaults to self_critique_bullet.run.
    """
    if smell_detector is None:
        from src.tools.quality import detect_ai_smell

        smell_detector = detect_ai_smell.run
    if self_critique_fn is None:
        from src.tools.quality import self_critique_bullet

        self_critique_fn = self_critique_bullet.run

    data = _as_dict(raw)
    if not isinstance(data, dict):
        return False, "Output is not a JSON object matching AdaptedCV."

    bullets: list[str] = []
    for section in data.get("sections") or []:
        bullets.extend(section.get("bullets") or [])
    if not bullets:
        return False, "AdaptedCV.sections has no bullets. Rewrite produced an empty CV."

    try:
        smell = json.loads(smell_detector(json.dumps({"text": "\n".join(bullets)})))
        score = int(smell.get("ai_smell_score", 0))
        if score >= 50:
            return False, (
                f"detect_ai_smell returned ai_smell_score={score} (>=50). "
                f"Issues: {smell.get('issues', [])[:3]}. "
                "Rewrite the flagged bullets in the candidate's voice."
            )
    except Exception:
        pass

    flagged: list[str] = []
    for bullet in bullets[:5]:
        try:
            critique = json.loads(self_critique_fn(json.dumps({"bullet": bullet})))
            if critique.get("issues"):
                flagged.append(f"{bullet[:80]}... → {critique['issues'][0]}")
        except Exception:
            continue
    if len(flagged) >= 3:
        return False, "self_critique_bullet flagged 3+ bullets:\n - " + "\n - ".join(flagged)
    return True, raw


def mirroring_under_threshold(raw: Any) -> Result:
    """Humanizer guardrail. Rejects outputs that mirror the JD too closely."""
    from src.tools.quality import detect_mirroring

    data = _as_dict(raw)
    if not isinstance(data, dict):
        return False, "Output is not a JSON object matching AuthenticityReport."

    cv_text = data.get("humanized_text") or data.get("cv_text") or ""
    job_text = data.get("job_text") or ""
    if not (cv_text and job_text):
        return True, raw  # defer when inputs aren't both present

    try:
        report = json.loads(
            detect_mirroring.run(json.dumps({"job_text": job_text, "cv_text": cv_text}))
        )
        similarity = float(report.get("similarity", 0.0))
        if similarity >= 0.30:
            return False, (
                f"detect_mirroring similarity={similarity:.2f} (>=0.30). "
                f"Phrases to rewrite: {report.get('mirrored_phrases', [])[:3]}. "
                "Use the candidate's own voice instead."
            )
    except Exception:
        pass
    return True, raw
