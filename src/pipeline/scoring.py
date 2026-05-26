"""Pure scoring and decision helpers for the run report.

Rule-based functions only — the LLM-backed enrichers (Opus decision helper,
Opus match classifier) remain in main.py because they wire to user-facing
warning helpers.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = [
    "NUMBER_RE",
    "CHECKLIST_STOPWORDS",
    "VERDICT_TIERS",
    "WEAK_WORDS",
    "STRONG_ACTION_VERBS",
    "compute_skill_alignment_matrix",
    "audit_quantification",
    "audit_weak_words",
    "extract_strong_verbs_from_jd",
    "checklist_tokens",
    "build_pre_submission_checklist",
    "estimate_score_uplift",
    "effort_impact_quadrant",
    "match_by_category",
    "status_badge",
    "decision_helper",
    "qualitative_match_by_category",
]

from src.pipeline.coercion import as_dict, as_list, as_list_of_dicts

NUMBER_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|k|m|b|x|million|billion|"
    r"hours|days|weeks|months|years|people|users|"
    r"customers|projects|teams|engineers|reports)?\b",
    re.I,
)

CHECKLIST_STOPWORDS = {
    "the", "a", "an", "is", "in", "on", "of", "to", "for", "with",
    "and", "or", "as", "by", "be", "are", "this", "that", "her",
    "his", "their", "from", "at", "than", "not", "no", "but",
    "candidate", "she", "he", "have", "has", "had", "may", "could",
    "would", "will", "which", "while", "el", "la", "los", "las",
    "de", "del", "y", "en", "un", "una", "que",
}

VERDICT_TIERS = [
    "✅ Apply — strong candidate",
    "✅ Apply, but address gaps in cover letter",
    "⚠️ Apply only if you can fix the red flags first",
    "❌ Skip — invest time in higher-fit roles",
]

WEAK_WORDS = {
    "responsible for":   ("led / drove / owned",          "implies passive ownership"),
    "duties included":   ("led / executed / owned",       "passive phrasing"),
    "helped with":       ("contributed to / supported",   "vague — quantify the contribution"),
    "worked on":         ("delivered / built / shipped",  "passive verb"),
    "involved in":       ("led / contributed to",         "vague involvement"),
    "various":           ("[specific number]",            "lacks concreteness"),
    "many":              ("[specific number]",            "lacks concreteness"),
    "several":           ("[specific number]",            "lacks concreteness"),
    "tasked with":       ("led / drove / executed",       "passive phrasing"),
    "synergy":           ("collaboration / integration",  "jargon — use plain language"),
    "go-getter":         ("[describe a result]",          "cliché"),
    "team player":       ("[describe collaborative win]", "cliché"),
    "results-driven":    ("[describe an actual result]",  "cliché"),
    "self-starter":      ("[describe an initiative]",     "cliché"),
    "passionate about":  ("[describe a tangible interest]", "weak/generic"),
    "hard-working":      ("[describe a hard-won win]",    "cliché"),
    "leveraged":         ("used / applied",               "overused jargon"),
    "spearheaded":       ("led / launched",               "overused"),
    "utilized":          ("used",                         "longer than needed"),
    "facilitated":       ("led / organized / ran",        "passive"),
    "in charge of":      ("led / owned",                  "passive"),
}

STRONG_ACTION_VERBS = {
    "leadership":    ["Led", "Directed", "Mentored", "Coached", "Championed", "Spearheaded", "Orchestrated"],
    "delivery":      ["Delivered", "Shipped", "Launched", "Released", "Deployed", "Rolled out"],
    "impact":        ["Drove", "Generated", "Increased", "Reduced", "Saved", "Accelerated", "Cut"],
    "build":         ["Built", "Designed", "Architected", "Engineered", "Developed", "Implemented"],
    "analysis":      ["Analyzed", "Evaluated", "Audited", "Identified", "Diagnosed"],
    "strategy":      ["Defined", "Established", "Created", "Formulated", "Planned"],
    "process":       ["Streamlined", "Optimized", "Improved", "Standardized", "Automated"],
    "collaboration": ["Partnered", "Coordinated", "Aligned", "Negotiated", "Influenced"],
}


def compute_skill_alignment_matrix(job: dict, candidate: dict) -> list[dict]:
    """For each job requirement, classify candidate coverage as full / partial /
    missing. Returns a list of {requirement, priority, category, status} dicts.
    """
    job = as_dict(job)
    candidate = as_dict(candidate)
    requirements = job.get("requirements") or []
    skills = [s.lower() for s in (candidate.get("skills") or []) if isinstance(s, str)]
    techs = [t.lower() for t in (job.get("tech_stack") or []) if isinstance(t, str)]
    wx_techs: list[str] = []
    for w in as_list_of_dicts(candidate.get("work_experience")):
        for t in (w.get("technologies") or []):
            if isinstance(t, str):
                wx_techs.append(t.lower())
    haystack = " ".join(skills + wx_techs).lower()

    matrix: list[dict] = []
    for r in requirements[:18]:
        if isinstance(r, dict):
            text = r.get("text", "")
            priority = r.get("priority", "")
            category = r.get("category", "")
        else:
            text = str(r)
            priority = ""
            category = ""
        rtext_low = text.lower()
        full = any(s and len(s) > 3 and s in rtext_low for s in skills) \
            or any(t in rtext_low for t in techs)
        partial = False
        if not full:
            tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9+/.\-]{2,}\b", rtext_low)
            for tok in tokens:
                if len(tok) >= 4 and tok in haystack:
                    partial = True
                    break
        status = "✅" if full else ("⚠️" if partial else "❌")
        matrix.append({
            "requirement": text[:120],
            "priority": priority or "—",
            "category": category or "—",
            "status": status,
        })
    return matrix


def audit_quantification(work_experience: Any, max_flagged: int = 12) -> list[dict]:
    """Flag bullets that don't contain a metric/number."""
    out: list[dict] = []
    for w in as_list_of_dicts(work_experience):
        title = w.get("title", "") or ""
        company = w.get("company", "") or ""
        for bullet in (w.get("bullets") or []):
            if not isinstance(bullet, str) or not bullet.strip():
                continue
            if not NUMBER_RE.search(bullet):
                out.append({
                    "title": title, "company": company, "bullet": bullet[:200],
                })
                if len(out) >= max_flagged:
                    return out
    return out


def audit_weak_words(work_experience: Any) -> list[dict]:
    """Find bullets containing weak buzzwords / passive phrasing."""
    out: list[dict] = []
    for w in as_list_of_dicts(work_experience):
        for bullet in (w.get("bullets") or []):
            if not isinstance(bullet, str) or not bullet.strip():
                continue
            low = bullet.lower()
            hits = [(weak, info) for weak, info in WEAK_WORDS.items() if weak in low]
            if hits:
                out.append({
                    "bullet": bullet[:200],
                    "weak_phrases": [w for w, _ in hits[:3]],
                    "suggestions": [s for _, (s, _) in hits[:3]],
                })
            if len(out) >= 12:
                return out
    return out


def extract_strong_verbs_from_jd(job: Any) -> list[str]:
    """Pull the verbs the JD uses most — the user can mirror their tone."""
    job = as_dict(job)
    resp_list = [r for r in (job.get("responsibilities") or []) if isinstance(r, str)]
    req_list: list[str] = []
    for r in (job.get("requirements") or []):
        if isinstance(r, dict):
            req_list.append(r.get("text", "") or "")
        elif isinstance(r, str):
            req_list.append(r)
    text = " ".join([" ".join(resp_list), " ".join(req_list)])
    if not text:
        return []
    verbs = re.findall(r"\b([A-Z]?[a-z]{4,})(?:\s|,|\.)", text)
    common = {"with", "from", "this", "that", "have", "must", "will", "their",
              "they", "your", "team", "role", "work", "year", "experience",
              "skill", "ability", "able", "such", "other", "also", "more",
              "into", "across", "through", "include", "including"}
    counts: dict[str, int] = {}
    for v in verbs:
        v_low = v.lower()
        if len(v_low) < 4 or v_low in common:
            continue
        if not v_low.endswith(("e", "d", "s", "g", "t", "y", "n")):
            continue
        counts[v_low] = counts.get(v_low, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:8]
    return [w.capitalize() for w, _ in top]


def checklist_tokens(s: str) -> set:
    """Significant-token set used for fuzzy dedupe in the pre-submission checklist."""
    x = re.sub(r"[^a-z0-9áéíóúñü ]+", " ", (s or "").lower())
    return {t for t in x.split() if len(t) > 2 and t not in CHECKLIST_STOPWORDS}


def build_pre_submission_checklist(report: dict) -> list[str]:
    """Collapse red flags, gaps, format issues, and prioritized changes into
    one ordered to-do list. Fuzzy-deduped so paraphrases of the same blocker
    don't appear twice.
    """
    items: list[str] = []
    for ev in as_list_of_dicts(report.get("evaluations")):
        for f in as_list(ev.get("red_flags"))[:2]:
            if isinstance(f, str):
                items.append(f)
    gap = as_dict(report.get("gap_analysis"))
    for g in (gap.get("critical_gaps") or []):
        if isinstance(g, str):
            items.append(f"Address gap: {g}")
    cf = as_dict(report.get("consolidated_feedback"))
    for ch in as_list_of_dicts(cf.get("prioritized_changes")):
        if (ch.get("impact") or "").lower() == "high":
            items.append(f"[{ch.get('change_type','edit')}] "
                          f"{ch.get('target_section','—')} — "
                          f"{ch.get('description','')}")
    ats = as_dict(report.get("ats_report"))
    missing = ats.get("missing_keywords") or []
    if missing:
        items.append("Inject these ATS keywords naturally: "
                      f"{', '.join(str(m) for m in missing[:8])}")
    for f in (ats.get("format_issues") or []):
        if isinstance(f, str):
            items.append(f"Fix format issue: {f}")

    out: list[str] = []
    token_sets: list[set] = []
    for it in items:
        clean = (it or "").strip()
        if not clean:
            continue
        toks = checklist_tokens(clean)
        is_dupe = False
        for existing in token_sets:
            if not existing or not toks:
                continue
            overlap = len(existing & toks)
            smaller = min(len(existing), len(toks))
            ratio = overlap / smaller if smaller else 0.0
            if overlap >= 4 and ratio >= 0.45:
                is_dupe = True
                break
        if not is_dupe:
            out.append(clean)
            token_sets.append(toks)
    return out[:20]


def estimate_score_uplift(report: dict) -> dict:
    """Naïve projection: if all high/medium/low changes land, where does the score go?"""
    current = report.get("overall_match_score", 0) or 0
    cf = as_dict(report.get("consolidated_feedback"))
    counts = {"high": 0, "medium": 0, "low": 0}
    for ch in as_list_of_dicts(cf.get("prioritized_changes")):
        impact = (ch.get("impact") or "medium").lower()
        counts[impact] = counts.get(impact, 0) + 1
    uplift = (counts.get("high", 0) * 6 +
              counts.get("medium", 0) * 3 +
              counts.get("low", 0) * 1)
    projected = min(95, current + uplift)
    return {
        "current": current,
        "projected": projected,
        "uplift": projected - current,
        "high": counts.get("high", 0),
        "medium": counts.get("medium", 0),
        "low": counts.get("low", 0),
    }


def effort_impact_quadrant(report: dict) -> dict[str, list[dict]]:
    """Bucket prioritized changes into a 2x2 (impact × effort) grid."""
    cf = as_dict(report.get("consolidated_feedback"))
    grid: dict[str, list[dict]] = {
        "high_low":  [],  # quick wins
        "high_high": [],
        "low_low":   [],
        "low_high":  [],
    }
    for ch in as_list_of_dicts(cf.get("prioritized_changes")):
        impact = "high" if (ch.get("impact") or "medium").lower() == "high" else "low"
        effort = "high" if (ch.get("effort") or "medium").lower() == "high" else "low"
        grid[f"{impact}_{effort}"].append(ch)
    return grid


def match_by_category(evaluations: Any) -> dict[str, int]:
    """Per-reviewer category → score, used for the bar chart."""
    out: dict[str, int] = {}
    role_to_label = {
        "hr": "Cultural / Soft Skills",
        "hiring": "Leadership / Impact",
        "tech": "Technical / Domain",
        "ats": "ATS / Keywords",
    }
    for ev in as_list_of_dicts(evaluations):
        role = (ev.get("agent_role") or "").lower()
        score = int(ev.get("fit_score") or 0)
        label = next((lbl for needle, lbl in role_to_label.items() if needle in role), "Other")
        out[label] = max(out.get(label, 0), score)
    return out


def status_badge(report: Any) -> tuple[str, str, str]:
    """Qualitative fit (emoji, label, recommendation) from structural signals."""
    report = as_dict(report)
    gap = as_dict(report.get("gap_analysis"))
    crit_gaps = len([g for g in (gap.get("critical_gaps") or []) if isinstance(g, str)])
    red_flags = sum(len(as_dict(ev).get("red_flags") or [])
                    for ev in (report.get("evaluations") or []))
    missing_kw = len(as_dict(report.get("ats_report")).get("missing_keywords") or [])

    if crit_gaps == 0 and red_flags == 0 and missing_kw <= 5:
        return ("🟢", "Strong fit",
                "Your profile aligns on the major dimensions. Polish the bullets and apply.")
    if crit_gaps <= 1 and red_flags <= 2:
        return ("🟡", "Solid fit with gaps",
                "Competitive — tighten the gaps below before submitting to lift interview odds.")
    if crit_gaps <= 3:
        return ("🟠", "Stretch role",
                "Notable gaps exist. Apply only if you can address the red flags in your cover letter.")
    return ("🔴", "Major mismatch",
            "Significant misalignment on hard requirements. Consider whether this fits your stage.")


def decision_helper(report: dict) -> dict:
    """'Should you apply?' from qualitative signals — no numeric scores."""
    report = as_dict(report)
    job = as_dict(report.get("job"))
    has_salary = bool(job.get("salary_range"))
    is_remote = (job.get("modality") or "").lower() in ("remote", "hybrid")
    gap = as_dict(report.get("gap_analysis"))
    crit_gaps = len([g for g in (gap.get("critical_gaps") or []) if isinstance(g, str)])
    red_flags = sum(len(as_dict(ev).get("red_flags") or [])
                    for ev in (report.get("evaluations") or []))

    pros: list[str] = []
    cons: list[str] = []
    if crit_gaps == 0:
        pros.append("No critical gaps")
    elif crit_gaps <= 2:
        cons.append(f"{crit_gaps} critical gap(s) to address")
    else:
        cons.append(f"{crit_gaps} critical gaps — significant retooling needed")
    if red_flags == 0:
        pros.append("No reviewer red flags")
    elif red_flags <= 2:
        cons.append(f"{red_flags} reviewer red flag(s)")
    else:
        cons.append(f"{red_flags} reviewer red flags")
    if is_remote:
        pros.append("Remote/hybrid friendly")
    elif job.get("modality"):
        cons.append(f"Modality: {job.get('modality')}")
    if has_salary:
        pros.append("Posting lists a salary range — you can negotiate")

    if crit_gaps == 0 and red_flags <= 1:
        verdict = VERDICT_TIERS[0]
    elif crit_gaps <= 1 and red_flags <= 3:
        verdict = VERDICT_TIERS[1]
    elif crit_gaps <= 3:
        verdict = VERDICT_TIERS[2]
    else:
        verdict = VERDICT_TIERS[3]

    return {"verdict": verdict, "pros": pros, "cons": cons}


def qualitative_match_by_category(evaluations: Any) -> list[dict]:
    """Rule-based fallback used when the Opus classifier is unavailable."""
    role_to_label = {
        "hr": "Cultural / Soft Skills",
        "hiring": "Leadership / Impact",
        "tech": "Technical / Domain",
        "ats": "ATS / Keywords",
    }
    out: list[dict] = []
    for ev in as_list_of_dicts(evaluations):
        role = (ev.get("agent_role") or "").lower()
        label = next((lbl for needle, lbl in role_to_label.items() if needle in role), "Other")
        strengths = len(ev.get("strengths") or [])
        weaknesses = len(ev.get("weaknesses") or [])
        red_flags = len(ev.get("red_flags") or [])
        if red_flags >= 1 or weaknesses > strengths + 1:
            band = "🔴 Weak"
        elif weaknesses >= strengths:
            band = "🟠 Partial"
        elif strengths >= weaknesses + 1 and weaknesses > 0:
            band = "🟡 Solid"
        else:
            band = "🟢 Strong"
        signal = (ev.get("strengths") or ev.get("weaknesses") or ["—"])[0]
        if not isinstance(signal, str):
            signal = "—"
        out.append({
            "category": label,
            "band": band,
            "signal": signal[:120],
            "reviewer": ev.get("agent_role", "—"),
        })
    return out
