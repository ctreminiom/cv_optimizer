"""LLM-backed and rule-based report enrichment helpers.

These functions transform a raw JobReport dict into the richer version
displayed in the Markdown/PDF output. They are separate from the report
builder (which assembles from task outputs) and the renderer (which writes).

Extracted from main.py (SRP Phase 3c). No logic changes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.pipeline.coercion import (
    as_dict as _as_dict,
)
from src.pipeline.coercion import (
    as_list as _as_list,
)
from src.pipeline.coercion import (
    as_list_of_dicts as _as_list_of_dicts,
)
from src.pipeline.scoring import (
    VERDICT_TIERS as _VERDICT_TIERS,
)
from src.pipeline.scoring import (
    decision_helper as _decision_helper,
)
from src.pipeline.scoring import (
    qualitative_match_by_category as _qualitative_match_by_category,
)
from src.presentation import warn as _warn

__all__ = [
    "decision_helper_with_opus",
    "classify_match_with_opus",
    "posting_freshness",
    "prescreen_with_haiku",
    "copy_job_source_as_pdf",
    "write_prescreen_stub",
]

# ── Freshness patterns (used by posting_freshness) ────────────────────────────

_FRESHNESS_BODY_PATTERNS = [
    (re.compile(r"\bposted[:\s]+(\d+)\s+hour", re.I), "hours"),
    (re.compile(r"\bposted[:\s]+(\d+)\s+day", re.I), "days"),
    (re.compile(r"\bposted[:\s]+(\d+)\s+week", re.I), "weeks"),
    (re.compile(r"\bposted[:\s]+(\d+)\s+month", re.I), "months"),
    (re.compile(r"\bhace\s+(\d+)\s+hora", re.I), "hours"),
    (re.compile(r"\bhace\s+(\d+)\s+d[ií]a", re.I), "days"),
    (re.compile(r"\bhace\s+(\d+)\s+semana", re.I), "weeks"),
    (re.compile(r"\bhace\s+(\d+)\s+mes", re.I), "months"),
    (re.compile(r"\b(\d+)\s+day(s)?\s+ago", re.I), "days"),
    (re.compile(r"\b(\d+)\s+week(s)?\s+ago", re.I), "weeks"),
    (re.compile(r"\b(\d+)\s+month(s)?\s+ago", re.I), "months"),
]

_FRESHNESS_DATE_PATTERN = re.compile(
    r"(?:posted on|published on|publicado el|fecha de publicaci[oó]n)[:\s]+"
    r"(\d{4})-(\d{1,2})-(\d{1,2})",
    re.I,
)


# ── posting_freshness ─────────────────────────────────────────────────────────


def posting_freshness(job_path: Path) -> str:
    """Return a freshness/urgency line. §3.6 — prefers a posted/published
    date parsed from the JD body when present (LinkedIn / Indeed /
    Computrabajo all embed one); falls back to file mtime only when the
    body is silent."""
    import datetime as _dt

    age_days: int | None = None
    source = "file mtime"
    try:
        if job_path.suffix.lower() in (".md", ".txt") and job_path.exists():
            text = job_path.read_text(encoding="utf-8", errors="ignore")[:6000]
            for pattern, unit in _FRESHNESS_BODY_PATTERNS:
                m = pattern.search(text)
                if m:
                    n = int(m.group(1))
                    if unit == "hours":
                        age_days = max(0, n // 24)
                    elif unit == "days":
                        age_days = n
                    elif unit == "weeks":
                        age_days = n * 7
                    elif unit == "months":
                        age_days = n * 30
                    source = f"posting body ({unit})"
                    break
            if age_days is None:
                m = _FRESHNESS_DATE_PATTERN.search(text)
                if m:
                    try:
                        posted = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                        age_days = (_dt.date.today() - posted).days
                        source = "posting body (date)"
                    except Exception:
                        pass

        if age_days is None:
            mtime = _dt.datetime.fromtimestamp(job_path.stat().st_mtime)
            age_days = (_dt.datetime.now() - mtime).days
            source = "file mtime"

        if age_days <= 1:
            return f"🟢 Fresh ({source}). Apply within the first wave."
        if age_days <= 7:
            return f"🟢 Recent — {age_days}d ({source}). Apply soon for the first review batch."
        if age_days <= 30:
            return f"🟡 {age_days}d old ({source}). Still worth applying; expect more competition."
        return f"🟠 Stale — {age_days}d ({source}). Verify the role is still open."
    except Exception:
        return "—"


# ── decision_helper_with_opus ─────────────────────────────────────────────────


def decision_helper_with_opus(report: dict) -> dict:
    """Opus 4.7 version of `decision_helper`. Produces a precise, role-and-
    candidate-specific 'Should you apply?' read: one of the four standard
    verdict tiers, a one-line rationale citing the decisive evidence, and
    pros/cons that quote concrete signals (specific gaps, reviewer flags,
    strengths) instead of templated counts.

    Falls back to the rule-based `decision_helper` on any failure.
    """
    try:
        from src.llm.client import get_default_client

        _llm = get_default_client()
    except Exception:
        return _decision_helper(report)

    report = _as_dict(report)
    job = _as_dict(report.get("job"))
    gap = _as_dict(report.get("gap_analysis"))
    ats = _as_dict(report.get("ats_report"))
    cf = _as_dict(report.get("consolidated_feedback"))

    evs = _as_list_of_dicts(report.get("evaluations"))
    reviewer_bundle = []
    for ev in evs:
        reviewer_bundle.append(
            {
                "reviewer": ev.get("agent_role", ""),
                "strengths": [s for s in (ev.get("strengths") or []) if isinstance(s, str)][:8],
                "weaknesses": [w for w in (ev.get("weaknesses") or []) if isinstance(w, str)][:8],
                "red_flags": [r for r in (ev.get("red_flags") or []) if isinstance(r, str)][:6],
            }
        )

    job_ctx = {
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "seniority": job.get("seniority", ""),
        "role_type": job.get("role_type", ""),
        "modality": job.get("modality", ""),
        "location": job.get("location", ""),
    }
    gap_ctx = {
        "critical_gaps": _as_list(gap.get("critical_gaps"))[:10],
        "minor_gaps": _as_list(gap.get("minor_gaps"))[:6],
    }
    ats_ctx = {
        "missing_keywords": _as_list(ats.get("missing_keywords"))[:12],
    }
    cf_ctx = {
        "common_strengths": _as_list(cf.get("common_strengths"))[:6],
        "common_weaknesses": _as_list(cf.get("common_weaknesses"))[:6],
    }
    salary_ctx = {
        "has_salary_data": bool(job.get("salary_range")),
    }

    prompt = f"""You are a senior career advisor giving a candidate a precise, evidence-grounded read on whether to apply to this specific role.

# Target role
{json.dumps(job_ctx, indent=2, ensure_ascii=False)}

# Reviewer feedback (HR, Hiring Manager, Senior Practitioner)
{json.dumps(reviewer_bundle, indent=2, ensure_ascii=False)}

# Gap analysis
{json.dumps(gap_ctx, indent=2, ensure_ascii=False)}

# ATS / missing keywords
{json.dumps(ats_ctx, indent=2, ensure_ascii=False)}

# Consolidated reviewer themes
{json.dumps(cf_ctx, indent=2, ensure_ascii=False)}

# Salary signal
{json.dumps(salary_ctx, indent=2, ensure_ascii=False)}

# Task
Produce a precise 'Should You Apply?' verdict tailored to THIS candidate and THIS role.

Output rules:
1. `verdict` MUST be exactly one of these four strings (copy verbatim):
   - "✅ Apply — strong candidate"
   - "✅ Apply, but address gaps in cover letter"
   - "⚠️ Apply only if you can fix the red flags first"
   - "❌ Skip — invest time in higher-fit roles"
2. `reason` is ONE sentence (max 220 chars) that names the 1-2 decisive factors driving the verdict. Cite specifics from the evidence (tool names, year gaps, seniority mismatch, etc.). NO generic phrases like "significant retooling needed" or "address gaps in cover letter."
3. `pros` is a list of 2-4 strings. Each MUST cite a concrete piece of evidence (a specific strength, a tool, a metric, a geographic/language match, a year range). NO templated phrases like "No critical gaps" or "Remote/hybrid friendly" — name the actual signal.
4. `cons` is a list of 2-5 strings. Each MUST cite a concrete piece of evidence (a specific missing tool, a named reviewer red flag, a recency gap with years, a seniority mismatch with role title). NO counts like "4 critical gaps" or "14 reviewer red flags" — name what they actually are.
5. Every pro and con must be its own distinct insight — do not pad. If there are only 2 real pros, list 2.
6. Each pro/con under 180 chars, no trailing period required.

Return ONLY a JSON object (no markdown fences, no preamble) with this exact schema:
{{
  "verdict": "one of the four strings above",
  "reason": "one-sentence rationale citing specifics",
  "pros": ["...", "..."],
  "cons": ["...", "..."]
}}"""

    from src.settings import get_settings as _gs

    model_id = _gs().model_opus
    try:
        content = _llm.complete(
            model=model_id,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        ).strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
        brace = content.find("{")
        if brace > 0:
            content = content[brace:]
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("Opus returned non-object")

        verdict = (result.get("verdict") or "").strip()
        if verdict not in _VERDICT_TIERS:
            for tier in _VERDICT_TIERS:
                if verdict and verdict[:1] == tier[:1]:
                    verdict = tier
                    break
            else:
                raise ValueError(f"verdict not in allowed tiers: {verdict!r}")

        reason = (result.get("reason") or "").strip()[:240]
        pros = [str(p).strip()[:200] for p in (result.get("pros") or []) if str(p).strip()][:4]
        cons = [str(c).strip()[:200] for c in (result.get("cons") or []) if str(c).strip()][:5]
        if not pros and not cons:
            raise ValueError("Opus returned empty pros and cons")

        return {"verdict": verdict, "reason": reason, "pros": pros, "cons": cons}
    except Exception as e:
        _warn(f"Opus decision-helper failed ({model_id}): {e}")
    return _decision_helper(report)


# ── classify_match_with_opus ──────────────────────────────────────────────────


def classify_match_with_opus(
    evaluations: Any, job: dict, ats_report: dict, gap_analysis: dict
) -> list[dict]:
    """Use Opus 4.7 to synthesize all reviewer feedback into a meaningful
    per-category fit assessment. Categories emerge from the actual evidence
    in the evaluations (Technical Skills, Domain Experience, Leadership,
    Cultural Fit, ATS/Keywords, etc.) rather than being hard-coded to one
    reviewer = one bucket. Bands are graded against evidence, not against
    a uniform Weak default.

    Falls back to the rule-based classifier on any failure.
    """
    try:
        from src.llm.client import get_default_client

        _llm = get_default_client()
    except Exception:
        return _qualitative_match_by_category(evaluations)

    evs = _as_list_of_dicts(evaluations)
    if not evs:
        return []

    reviewer_bundle = []
    for ev in evs:
        reviewer_bundle.append(
            {
                "reviewer": ev.get("agent_role", ""),
                "strengths": [s for s in (ev.get("strengths") or []) if isinstance(s, str)][:12],
                "weaknesses": [w for w in (ev.get("weaknesses") or []) if isinstance(w, str)][:12],
                "red_flags": [r for r in (ev.get("red_flags") or []) if isinstance(r, str)][:6],
            }
        )

    job_ctx = {
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "seniority": job.get("seniority", ""),
        "role_type": job.get("role_type", ""),
    }
    ats_ctx = {
        "missing_keywords": _as_list(ats_report.get("missing_keywords"))[:15],
        "overused_keywords": _as_list(ats_report.get("overused_keywords"))[:6],
    }
    gap_ctx = {
        "critical_gaps": _as_list(gap_analysis.get("critical_gaps"))[:8],
        "framing_opportunities": _as_list(gap_analysis.get("framing_opportunities"))[:5],
    }

    prompt = f"""You are a senior talent assessor synthesizing multiple reviewer perspectives into a fit assessment broken down by meaningful match categories.

# Reviewer feedback (HR, Hiring Manager, Senior Practitioner)
{json.dumps(reviewer_bundle, indent=2, ensure_ascii=False)}

# Target role
{json.dumps(job_ctx, indent=2, ensure_ascii=False)}

# ATS / keywords context
{json.dumps(ats_ctx, indent=2, ensure_ascii=False)}

# Gap analysis
{json.dumps(gap_ctx, indent=2, ensure_ascii=False)}

# Task
Identify 5-8 meaningful match categories that emerge from the evidence above (examples — pick what fits, invent others if needed):
- Technical Skills / Tools
- Domain Experience (vertical/industry)
- Leadership & Ownership
- Quantified Outcomes / Track Record
- Communication & Soft Skills
- Cultural / Geographic Fit
- ATS / Keywords
- Education & Credentials
- Seniority & Scope

For EACH category, assess fit using exactly one of these bands — grade against the EVIDENCE, do NOT default everything to Weak:
- "🟢 Strong" — clearly meets or exceeds the bar; multiple reviewers cite positive evidence
- "🟡 Solid" — meets the bar; minor gaps only
- "🟠 Partial" — partial fit with notable gaps
- "🔴 Weak" — clear deficiency; multiple reviewers flagged it

Discrimination is critical. A real candidate has strengths AND weaknesses — at least one category should be Strong or Solid if any reviewer cited a clear positive signal (e.g., bilingual fluency, geographic alignment, multi-region experience). Reserve 🔴 Weak for genuine deficiencies, not modest gaps.

For each category, also write a one-line `signal` (max 140 chars) summarizing the key evidence drawn from reviewer feedback.

Return ONLY a JSON array (no markdown fences, no preamble, no trailing commentary) with this exact schema:
[
  {{
    "category": "string (the category label)",
    "band": "🟢 Strong" | "🟡 Solid" | "🟠 Partial" | "🔴 Weak",
    "signal": "string — one-line evidence summary"
  }}
]"""

    from src.settings import get_settings as _gs

    model_id = _gs().model_opus
    try:
        content = _llm.complete(
            model=model_id,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        ).strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
        bracket = content.find("[")
        if bracket > 0:
            content = content[bracket:]
        result = json.loads(content)
        if isinstance(result, list) and result:
            cleaned = []
            for r in result:
                if not isinstance(r, dict):
                    continue
                cat = (r.get("category") or "").strip()
                band = (r.get("band") or "").strip()
                signal = (r.get("signal") or "").strip()
                if cat and band:
                    cleaned.append(
                        {
                            "category": cat,
                            "band": band,
                            "signal": signal[:160],
                            "reviewer": "consensus",
                        }
                    )
            if cleaned:
                return cleaned
    except Exception as e:
        _warn(f"Opus match-classification failed ({model_id}): {e}")
    return _qualitative_match_by_category(evaluations)


# ── prescreen_with_haiku ──────────────────────────────────────────────────────


def prescreen_with_haiku(cv_path: Path, job_path: Path) -> dict:
    """Cheap one-shot pre-screen call. Returns:
        {"proceed": bool, "reason": str, "verdict": str}
    Falls open (proceed=True) on any failure so we never block on infra
    errors. §3.1."""
    try:
        from src.llm.client import get_default_client

        _llm = get_default_client()
    except Exception:
        return {
            "proceed": True,
            "reason": "LLM client unavailable — skipping prescreen",
            "verdict": "unknown",
        }

    def _read_text(p: Path, limit: int = 4000) -> str:
        try:
            if p.suffix.lower() in (".md", ".txt"):
                return p.read_text(encoding="utf-8", errors="ignore")[:limit]
            if p.suffix.lower() == ".pdf":
                try:
                    from pypdf import PdfReader

                    pages = PdfReader(str(p)).pages[:2]
                    return "\n".join(pg.extract_text() or "" for pg in pages)[:limit]
                except Exception:
                    return ""
            if p.suffix.lower() == ".docx":
                try:
                    from docx import Document

                    doc = Document(str(p))
                    return "\n".join(par.text for par in doc.paragraphs[:80])[:limit]
                except Exception:
                    return ""
        except Exception:
            return ""
        return ""

    cv_text = _read_text(cv_path, 3500)
    jd_text = _read_text(job_path, 4000)
    if not jd_text:
        return {"proceed": True, "reason": "could not extract JD text", "verdict": "unknown"}

    prompt = (
        "You are a strict no-fluff hiring screener. Given the candidate's CV "
        "and the job description, decide whether it is worth investing 15 "
        "minutes of expensive multi-agent analysis on this pair. Return ONLY "
        "valid JSON, no preamble:\n"
        '{"verdict": "proceed" | "skip", "reason": "<one sentence>"}\n\n'
        "Skip ONLY if the candidate fails MULTIPLE hard must-haves simultaneously "
        "(e.g. wrong language, wrong country with no remote option, mandatory "
        "credential the candidate clearly lacks AND seniority mismatch). When "
        "in doubt, proceed.\n\n"
        f"=== CV (excerpt) ===\n{cv_text}\n\n"
        f"=== Job Description ===\n{jd_text}\n"
    )
    from src.settings import get_settings as _gs

    try:
        content = _llm.complete(
            model=_gs().model_haiku,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        ).strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
        data = json.loads(content)
        verdict = (data.get("verdict") or "").lower().strip()
        reason = (data.get("reason") or "").strip()
        return {
            "proceed": verdict != "skip",
            "verdict": verdict or "unknown",
            "reason": reason or "—",
        }
    except Exception as e:
        _warn(f"Prescreen call failed: {e} — proceeding with full run")
        return {"proceed": True, "reason": f"prescreen error: {e}", "verdict": "unknown"}


# ── copy_job_source_as_pdf ────────────────────────────────────────────────────


def copy_job_source_as_pdf(job_path: Path, target_dir: Path) -> Path | None:
    """Place a copy of the source job posting inside `target_dir` as a PDF.

    - `.pdf` sources are copied verbatim.
    - `.md` / `.txt` sources are rendered through `write_pdf_from_markdown`
      (txt is wrapped in a fenced code block to preserve formatting).
    - Anything else falls back to a verbatim copy.

    Returns the path written, or None on failure.
    """
    import shutil

    try:
        if not (job_path.exists() and job_path.is_file()):
            return None
        ext = job_path.suffix.lower()
        if ext == ".pdf":
            dest = target_dir / job_path.name
            shutil.copy2(job_path, dest)
            return dest
        dest = target_dir / (job_path.stem + ".pdf")
        if ext in (".md", ".txt"):
            text = job_path.read_text(encoding="utf-8", errors="ignore")
            md_text = text if ext == ".md" else f"```\n{text}\n```"
            from src.pdf_renderer import write_pdf_from_markdown

            write_pdf_from_markdown(md_text, dest)
            return dest
        dest = target_dir / job_path.name
        shutil.copy2(job_path, dest)
        return dest
    except Exception as e:
        _warn(f"Could not copy job source as PDF: {e}")
        return None


# ── write_prescreen_stub ──────────────────────────────────────────────────────


def write_prescreen_stub(
    target_dir: Path, job_path: Path, cv_path: Path, prescreen: dict
) -> Path | None:
    """Write a tiny report.md for jobs the prescreen skipped — keeps the
    output tree complete without spending the full crew budget. §3.1."""
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        md_path = target_dir / "report.md"
        import datetime as _dt

        ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        body = (
            f"# Resume Recommendation Report\n"
            f"## {job_path.stem}\n\n"
            f"- **Status:** ⏭️ Pre-screen SKIP — invest time elsewhere\n"
            f"- **Generated:** {ts}\n\n"
            f"## ⏭️ Pre-screen decision\n\n"
            f"> **Reason:** {prescreen.get('reason', '—')}\n\n"
            f"The cheap Haiku pre-screen judged this pair to be a multi-hard-"
            f"must-have mismatch and skipped the full crew to save budget. "
            f"To force a full analysis anyway, re-run with `--no-prescreen`.\n\n"
            f"## Source files\n\n"
            f"- **CV:** `{cv_path}`\n"
            f"- **Job posting:** `{job_path}`\n"
        )
        out_path: Path | None = None
        pdf_path = target_dir / "report.pdf"
        try:
            from src.pdf_renderer import write_pdf_from_markdown

            write_pdf_from_markdown(body, pdf_path)
            out_path = pdf_path
        except Exception as pdf_e:
            _warn(f"Could not render prescreen report.pdf, falling back to .md: {pdf_e}")
            md_path.write_text(body, encoding="utf-8")
            out_path = md_path
        copy_job_source_as_pdf(job_path, target_dir)
        return out_path
    except Exception as e:
        _warn(f"Could not write prescreen stub: {e}")
        return None
