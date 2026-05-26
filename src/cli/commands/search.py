"""CLI command handler for the `search` subcommand.

Extracted from main.py (SRP Phase 3e). No logic changes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from src.company import (
    KNOWN_CR_COMPANIES as _KNOWN_CR_COMPANIES,
    resolve_company_domain as _resolve_company_domain,
)
from src.pipeline.coercion import (
    as_dict as _as_dict,
    as_list as _as_list,
    as_list_of_dicts as _as_list_of_dicts,
)
from src.presentation import (
    HAS_RICH as _HAS_RICH,
    Panel,
    Table,
    banner as _banner,
    console as _console,
    err as _err,
    info as _info,
    ok as _ok,
    warn as _warn,
)

__all__ = ["cmd_search"]

class _FallbackQ:
    """Minimal questionary-compatible prompts using plain input(), used when questionary is absent."""

    class _Text:
        def __init__(self, question: str, default: str = "", validate=None):
            self._q, self._d, self._v = question, default, validate

        def ask(self) -> str | None:
            hint = f" [{self._d}]" if self._d else ""
            while True:
                try:
                    val = input(f"{self._q}{hint}: ").strip()
                except (KeyboardInterrupt, EOFError):
                    print()
                    return None
                if not val:
                    val = self._d
                if self._v:
                    result = self._v(val)
                    if result is not True:
                        print(f"  ⚠  {result}")
                        continue
                return val

    class _Select:
        def __init__(self, question: str, choices: list, default: str = ""):
            self._q, self._choices, self._d = question, choices, default

        def ask(self) -> str | None:
            print(f"{self._q}")
            for i, c in enumerate(self._choices, 1):
                marker = " (default)" if c == self._d else ""
                print(f"  {i}. {c}{marker}")
            def_idx = (self._choices.index(self._d) + 1) if self._d in self._choices else 1
            while True:
                try:
                    raw = input(f"Choice [1-{len(self._choices)}] (default {def_idx}): ").strip()
                except (KeyboardInterrupt, EOFError):
                    print()
                    return None
                if not raw:
                    return self._d or self._choices[0]
                if raw in self._choices:
                    return raw
                if raw.isdigit() and 1 <= int(raw) <= len(self._choices):
                    return self._choices[int(raw) - 1]
                print(f"  ⚠  Enter a number 1–{len(self._choices)}")

    class _Confirm:
        def __init__(self, question: str, default: bool = True):
            self._q, self._d = question, default

        def ask(self) -> bool | None:
            hint = "Y/n" if self._d else "y/N"
            try:
                raw = input(f"{self._q} [{hint}]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print()
                return None
            if not raw:
                return self._d
            return raw in ("y", "yes")

    @staticmethod
    def text(question: str, default: str = "", validate=None) -> "_FallbackQ._Text":
        return _FallbackQ._Text(question, default, validate)

    @staticmethod
    def select(question: str, choices: list, default: str = "") -> "_FallbackQ._Select":
        return _FallbackQ._Select(question, choices, default)

    @staticmethod
    def confirm(question: str, default: bool = True) -> "_FallbackQ._Confirm":
        return _FallbackQ._Confirm(question, default)


def _dedupe_concatenated_default(value: str) -> str:
    """If a wizard default got concatenated with user input (e.g. questionary
    pre-fills a default that the user types over without clearing), the result
    can look like "Costa RicaCosta Rica". Detect and collapse such duplicates.

    Approach: if the string is exactly two halves that are the same when
    case-insensitively compared, return one half. Otherwise, return as-is.
    """
    if not value:
        return value
    n = len(value)
    if n % 2 != 0:
        return value
    half = n // 2
    if value[:half].lower() == value[half:].lower():
        return value[:half]
    return value


def _interactive_search_wizard(args: argparse.Namespace) -> argparse.Namespace | None:
    """Prompt interactively for all search parameters. Returns None if user cancels."""
    try:
        import questionary as _q  # type: ignore
    except ImportError:
        _warn("questionary not installed — using plain input() prompts as fallback")
        _q = _FallbackQ  # type: ignore

    _banner("JOB SEARCH — Interactive Setup")

    cv_default = str(args.cv) if args.cv else ""
    cv_input = _q.text(
        "Master CV file (.docx or .pdf):",
        default=cv_default,
    ).ask()
    if cv_input is None:
        return None
    args.cv = Path(cv_input.strip())

    location = _q.text(
        "Target location:",
        default=args.location or "Costa Rica",
    ).ask()
    if location is None:
        return None
    args.location = _dedupe_concatenated_default(location.strip())

    seniority = _q.select(
        "Seniority level:",
        choices=["junior", "mid", "senior", "lead"],
        default=args.seniority or "mid",
    ).ask()
    if seniority is None:
        return None
    args.seniority = seniority

    modality_default = "remote" if args.remote else (args.modality or "any")
    modality = _q.select(
        "Work modality:",
        choices=["any", "remote", "hybrid", "on_site"],
        default=modality_default,
    ).ask()
    if modality is None:
        return None
    args.modality = modality
    args.remote = modality == "remote"

    role = _q.text(
        "Role keywords (comma-separated, blank = auto-detect from CV):",
        default=args.role or "",
    ).ask()
    if role is None:
        return None
    args.role = role.strip() or None

    keywords = _q.text(
        "Additional keywords (comma-separated, e.g. kubernetes,grpc):",
        default=args.keywords or "",
    ).ask()
    if keywords is None:
        return None
    args.keywords = keywords.strip() or None

    contract_type = _q.select(
        "Contract type:",
        choices=["any", "full_time", "contract", "part_time", "internship"],
        default=args.contract_type or "any",
    ).ask()
    if contract_type is None:
        return None
    args.contract_type = None if contract_type == "any" else contract_type

    min_match_raw = _q.text(
        "Minimum match score (0–100, 0 = show all):",
        default=str(args.min_match or 0),
        validate=lambda v: (v.isdigit() and 0 <= int(v) <= 100) or "Enter a number 0–100",
    ).ask()
    if min_match_raw is None:
        return None
    args.min_match = int(min_match_raw)

    max_results_raw = _q.text(
        "Maximum number of results:",
        default=str(args.max_results or 20),
        validate=lambda v: (v.isdigit() and int(v) > 0) or "Enter a positive number",
    ).ask()
    if max_results_raw is None:
        return None
    args.max_results = int(max_results_raw)

    print()
    _banner("Search Configuration — Confirm")
    rows = [
        ("CV",          str(args.cv)),
        ("Location",    args.location),
        ("Seniority",   args.seniority),
        ("Modality",    args.modality),
    ]
    if args.role:
        rows.append(("Roles", args.role))
    if args.keywords:
        rows.append(("Keywords", args.keywords))
    if args.contract_type:
        rows.append(("Contract", args.contract_type))
    rows += [
        ("Min match",   f"{args.min_match}/100"),
        ("Max results", str(args.max_results)),
    ]
    for label, value in rows:
        print(f"  {label:<14}: {value}")
    print()

    confirmed = _q.confirm("Proceed with this search?", default=True).ask()
    if not confirmed:
        _info("Search cancelled.")
        return None
    return args


from src.cli.utils import (
    SENIORITY_ORDER as _SENIORITY_ORDER,
    seniority_levels as _seniority_levels,
    slugify as _slugify,
)


_CLOSED_PHRASES = [
    "no longer accepting applications",
    "this job is no longer available",
    "this posting has expired",
    "job is closed",
    "position has been filled",
    "posting is closed",
    "application deadline has passed",
    "no longer accepting",
    "job no longer available",
    "listing has expired",
    "this job listing has expired",
    "applications are closed",
    # Additional patterns commonly seen on Workday / Greenhouse / Lever / Smart-
    # Recruiters / ICIMS that indicate a closed or removed posting.
    "this requisition is no longer active",
    "this requisition is closed",
    "this opportunity is no longer available",
    "the job you are looking for is no longer available",
    "this job has been filled",
    "this role has been filled",
    "the position you are looking for is no longer",
    "we are no longer accepting applications",
    "applications are no longer being accepted",
    "this position is closed",
    "this position is no longer available",
    # 404 / not-found redirects (some ATSes show a generic page)
    "page not found",
    "we couldn't find that page",
    "the page you are looking for does not exist",
    "404 not found",
    "oops! we can't find that page",
    # Spanish equivalents
    "vacante cerrada",
    "puesto cubierto",
    "esta vacante ya no está disponible",
    "esta posición ya no está disponible",
    "ya no se aceptan aplicaciones",
    "ya no se aceptan postulaciones",
]


# ─── URL / listing classifiers ────────────────────────────────────────────
# Implementations live in src/pipeline/url_filters.py. Underscore aliases
# preserve the legacy names used at call sites in this file.

from src.pipeline.url_filters import (
    COSTA_RICA_TERMS as _COSTA_RICA_TERMS,
    DOMAIN_TO_SOURCE as _DOMAIN_TO_SOURCE,
    LINKEDIN_AGGREGATOR_PATTERNS as _LINKEDIN_AGGREGATOR_PATTERNS,
    LOGIN_WALL_PHRASES as _LOGIN_WALL_PHRASES,
    PROFILE_URL_PATTERNS as _PROFILE_URL_PATTERNS,
    REMOTE_TERMS as _REMOTE_TERMS,
    SLUG_STOP_WORDS as _SLUG_STOP_WORDS,
    STALE_AGE_PATTERNS as _STALE_AGE_PATTERNS,
    content_matches_url_slug as _content_matches_url_slug,
    is_linkedin_category_aggregator as _is_linkedin_category_aggregator,
    is_location_relevant as _is_location_relevant,
    is_login_walled as _is_login_walled,
    is_stale_listing as _is_stale_listing,
    is_user_or_company_profile as _is_user_or_company_profile,
    normalize_source_from_url as _normalize_source_from_url,
    summarize_extracted_content as _summarize_extracted_content,
    url_slug_tokens as _url_slug_tokens,
)


# ──────────────────────────────────────────────────────────────────────────────
# Per-listing content parsing — extract structured fields from the Tavily-fetched
# page body so the report's table can be populated with real values instead of "—".
# ──────────────────────────────────────────────────────────────────────────────

_MODALITY_PATTERNS = [
    (re.compile(r"\b(fully\s+remote|100%\s+remote|remote[- ]first|work\s+from\s+home|"
                r"trabaja\s+desde\s+casa|teletrabajo|home\s+office)\b", re.I), "remote"),
    (re.compile(r"\b(hybrid|h[ií]brido|mixto|home\+office)\b", re.I), "hybrid"),
    (re.compile(r"\b(on[- ]site|on[- ]premises|presencial|in[- ]office)\b", re.I), "on_site"),
    (re.compile(r"\bremote\b", re.I), "remote"),
]

_CONTRACT_PATTERNS = [
    (re.compile(r"\b(full[- ]time|tiempo\s+completo|jornada\s+completa)\b", re.I), "full_time"),
    (re.compile(r"\b(part[- ]time|medio\s+tiempo|jornada\s+parcial)\b", re.I), "part_time"),
    (re.compile(r"\b(contract|contractor|freelance|por\s+contrato)\b", re.I), "contract"),
    (re.compile(r"\b(internship|intern|pasant[ií]a|practicante)\b", re.I), "internship"),
]

_SENIORITY_PATTERNS = [
    (re.compile(r"\b(staff|principal\s+engineer|principal\b)\b", re.I), "principal"),
    (re.compile(r"\b(lead|tech\s+lead|team\s+lead|líder\s+t[eé]cnico)\b", re.I), "lead"),
    (re.compile(r"\b(senior|sr\.|sr |senior\s+ii|sr\s+ii|jefe)\b", re.I), "senior"),
    (re.compile(r"\b(mid[- ]level|mid\b|intermediate|semi[- ]senior|ssr\b)\b", re.I), "mid"),
    (re.compile(r"\b(junior|jr\.|jr |entry[- ]level|associate)\b", re.I), "junior"),
]

# Years of experience: "5+ years", "3-5 years experience", "5 años de experiencia"
_EXPERIENCE_PATTERN = re.compile(
    r"\b(\d{1,2})\s*(?:\+|to|-|–)?\s*(?:\d{1,2})?\s*(?:years?|años?|yrs?)"
    r"(?:\s+of)?\s*(?:experience|experien[cz]ia|exp\.?)\b",
    re.I,
)

# Salary patterns — USD, CRC, EUR; ranges
_SALARY_PATTERN = re.compile(
    r"(?:\$|US\$|USD\s*|€|EUR\s*|₡|CRC\s*)\s*"
    r"(\d{1,3}(?:[,.\s]\d{3})*(?:\.\d+)?\s*K?)"
    r"(?:\s*[-–to]+\s*"
    r"(?:\$|US\$|USD\s*|€|EUR\s*|₡|CRC\s*)?\s*"
    r"(\d{1,3}(?:[,.\s]\d{3})*(?:\.\d+)?\s*K?))?"
    r"\s*(?:per\s+year|/year|/yr|/hour|/hr|annually|anual|al\s+año|/month|/mes|monthly)?",
    re.I,
)

# Common technical / role-relevant tokens — used both as tech stack hints and
# as candidate-skill match targets. The list is broad on purpose; we prefer
# false positives we can filter later over missing real keywords.
_TECH_KEYWORDS = {
    # Languages
    "python", "java", "javascript", "typescript", "go", "golang", "rust", "ruby",
    "kotlin", "swift", "scala", "c++", "c#", ".net", "php", "perl", "r",
    # Frameworks / libs
    "react", "vue", "angular", "next.js", "nestjs", "node.js", "nodejs", "django",
    "flask", "fastapi", "spring", "spring boot", "rails", "laravel", "express",
    # Cloud / infra
    "aws", "azure", "gcp", "google cloud", "kubernetes", "k8s", "docker", "terraform",
    "ansible", "jenkins", "circleci", "github actions", "gitlab ci",
    # Data
    "sql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "kafka",
    "spark", "hadoop", "snowflake", "databricks", "airflow", "dbt", "tableau",
    "power bi", "looker",
    # Methodologies / PM tools
    "agile", "scrum", "kanban", "safe", "waterfall", "lean", "six sigma",
    "jira", "confluence", "asana", "trello", "monday", "clickup", "notion",
    "ms project", "smartsheet", "azure devops", "miro",
    # Roles / certs
    "pmp", "csm", "psm", "popm", "cspo", "itil", "prince2",
    # Misc
    "rest", "graphql", "grpc", "microservices", "ci/cd", "tdd", "bdd",
    "machine learning", "ml", "ai", "llm", "rag", "nlp", "computer vision",
}

# Section headers commonly found in job descriptions (English + Spanish).
_REQUIREMENTS_HEADERS = re.compile(
    r"^\s*(?:#+\s*)?(?:requirements?|qualifications?|what we['']re looking for|"
    r"what you['']ll need|skills?|requisitos|perfil|qualifica(?:tion|ç)?(?:s|es)?|"
    r"about you|you have|must have|nice[- ]to[- ]have|preferred|deber[áa]s?\s+tener|"
    r"experiencia\s+requerida|conocimientos)\s*:?\s*$",
    re.I,
)
_BENEFITS_HEADERS = re.compile(
    r"^\s*(?:#+\s*)?(?:benefits?|perks|what we offer|why join us|compensation|"
    r"beneficios|qu[eé]\s+ofrecemos|paquete|prestaciones)\s*:?\s*$",
    re.I,
)
_RESPONSIBILITIES_HEADERS = re.compile(
    r"^\s*(?:#+\s*)?(?:responsibilities|what you['']ll do|the role|day[- ]to[- ]day|"
    r"key\s+responsibilities|responsabilidades|funciones|qu[eé]\s+har[áa]s)\s*:?\s*$",
    re.I,
)
_SECTION_END = re.compile(r"^\s*(?:#+\s+|---+|\*{3,}|=+)", re.I)


def _extract_section_bullets(content: str, header_re: re.Pattern,
                             max_bullets: int = 8) -> list[str]:
    """Extract bullet/list items under a markdown-ish section heading."""
    if not content:
        return []
    lines = content.splitlines()
    bullets: list[str] = []
    in_section = False
    for raw in lines:
        line = raw.rstrip()
        if header_re.match(line):
            in_section = True
            continue
        if not in_section:
            continue
        # End of section: a new header line / horizontal rule
        if line and _SECTION_END.match(line):
            stripped = line.strip()
            # Markdown headings (#) end the section
            if stripped.startswith("#"):
                break
        # Capture bullets ("-", "*", "•", numbered "1.")
        m = re.match(r"^\s*(?:[-*•▪◦·]|\d+[.)])\s+(.*\S)\s*$", line)
        if m:
            text = m.group(1).strip()
            # Drop markdown link/image syntax
            text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
            text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text).strip()
            if 5 < len(text) < 250:
                bullets.append(text)
                if len(bullets) >= max_bullets:
                    break
    return bullets


def _parse_job_fields_from_content(content: str, title: str = "") -> dict:
    """Heuristically extract structured job-table fields from a job description.

    Returns dict with any of: modality, contract_type, seniority, experience_years,
    salary_hint, tech_stack (list), requirements_summary (list), benefits (str),
    responsibilities (list).

    `title`, when provided, is used for seniority detection (more reliable than
    the body, where words like "lead" can appear as verbs).
    """
    out: dict = {}
    if not content:
        return out

    # Modality (first match wins, prefer specific over generic).
    for pat, label in _MODALITY_PATTERNS:
        if pat.search(content):
            out["modality"] = label
            break

    # Contract type.
    for pat, label in _CONTRACT_PATTERNS:
        if pat.search(content):
            out["contract_type"] = label
            break

    # Seniority — prefer title detection (verbs like "lead" pollute body matches).
    seniority_haystack = title if title else content
    for pat, label in _SENIORITY_PATTERNS:
        if pat.search(seniority_haystack):
            out["seniority"] = label
            break
    # If we didn't get a hit from the title, also try a high-confidence
    # body match (only `senior`/`junior`/`mid` near the start of the doc).
    if "seniority" not in out and content:
        first_block = content[:400]
        for pat, label in _SENIORITY_PATTERNS:
            if pat.search(first_block):
                out["seniority"] = label
                break

    # Experience years.
    m = _EXPERIENCE_PATTERN.search(content)
    if m:
        out["experience_years"] = f"{m.group(1)}+ years"

    # Salary.
    m = _SALARY_PATTERN.search(content)
    if m:
        low, high = m.group(1), m.group(2)
        if low and high:
            out["salary_hint"] = f"{low.strip()} – {high.strip()}"
        elif low and len(low) >= 2:
            out["salary_hint"] = low.strip()

    # Tech stack — match against curated keyword set.
    lower = content.lower()
    found_tech: list[str] = []
    for kw in _TECH_KEYWORDS:
        # Word-boundary match for short tokens; substring for multi-word tokens.
        if " " in kw or "/" in kw or "." in kw or "+" in kw:
            if kw in lower:
                found_tech.append(kw)
        else:
            if re.search(rf"\b{re.escape(kw)}\b", lower):
                found_tech.append(kw)
    if found_tech:
        out["tech_stack"] = sorted(set(found_tech))[:20]

    # Section-based extraction.
    reqs = _extract_section_bullets(content, _REQUIREMENTS_HEADERS, max_bullets=8)
    if reqs:
        out["requirements_summary"] = reqs

    resps = _extract_section_bullets(content, _RESPONSIBILITIES_HEADERS, max_bullets=6)
    if resps:
        out["responsibilities"] = resps

    benefits = _extract_section_bullets(content, _BENEFITS_HEADERS, max_bullets=6)
    if benefits:
        out["benefits"] = "; ".join(benefits)

    return out


def _expand_skill_tokens(skills: list[str]) -> list[str]:
    """Split compound/grouped skills (e.g. "Agile/SAFe", "CI/CD",
    "Project Management & Delivery") into individual searchable tokens.
    Also strips parenthetical context like "(SAFe Agile Academy, 2023)" before splitting."""
    tokens: list[str] = []
    for s in skills or []:
        if not s:
            continue
        # Strip parenthetical content (year, issuer) — leaves the cert/skill name.
        cleaned = re.sub(r"\s*\([^)]*\)", "", s).strip()
        # Split on common separators while preserving multi-word phrases.
        parts = re.split(r"\s*[/&,|]\s*|\s+and\s+", cleaned)
        for p in parts:
            p = p.strip().rstrip(".:")
            # Drop tokens with unbalanced parens or absurd length.
            if "(" in p or ")" in p or len(p) < 3 or len(p) > 60:
                continue
            tokens.append(p)
    # Dedup case-insensitively while preserving order.
    seen, out = set(), []
    for t in tokens:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _compute_match_score(opp: dict, candidate_skills: list[str],
                         candidate_titles: list[str]) -> tuple[int, str]:
    """Compute a 0–100 match score for one opportunity against the candidate profile.

    Score components (capped at 100):
      • 55 pts for skill keyword overlap — full credit at 4+ unique hits
      • 30 pts for role-title token overlap — full credit at 3+ token hits
      • 15 pts seniority match bonus (when both known)
    Returns (score, rationale_string).
    """
    haystack_parts = [
        opp.get("snippet") or "",
        opp.get("title") or "",
        " ".join(opp.get("requirements_summary") or []),
        " ".join(opp.get("responsibilities") or []),
        " ".join(opp.get("tech_stack") or []),
    ]
    haystack = " ".join(haystack_parts).lower()

    if not haystack.strip():
        return 0, ""

    # Expand compound skills into individual tokens for better matching.
    expanded_skills = _expand_skill_tokens(candidate_skills)

    # Skill overlap (case-insensitive whole-word for single tokens, substring for phrases).
    skill_hits: list[str] = []
    seen_low: set = set()
    for s in expanded_skills:
        s_low = s.lower().strip()
        if len(s_low) < 3 or s_low in seen_low:
            continue
        seen_low.add(s_low)
        matched = False
        if " " in s_low or "-" in s_low or "+" in s_low or "." in s_low:
            if s_low in haystack:
                matched = True
        else:
            if re.search(rf"\b{re.escape(s_low)}\b", haystack):
                matched = True
        if matched:
            skill_hits.append(s)

    skill_pts = 0
    if expanded_skills:
        # Full credit at 4 unique hits — easier than the previous 8.
        skill_pts = round(55 * min(1.0, len(skill_hits) / 4.0))

    # Title-token overlap (skip filler words and single-letter tokens).
    title_hits: list[str] = []
    _filler = {"and", "the", "for", "with", "your", "team", "manager",
               "specialist", "executive", "coordinator", "leader"}
    seen_tok: set = set()
    for t in candidate_titles or []:
        for token in (t or "").split():
            tok = token.lower().strip(".,;:()-")
            if len(tok) < 4 or tok in _filler or tok in seen_tok:
                continue
            seen_tok.add(tok)
            if re.search(rf"\b{re.escape(tok)}\b", haystack):
                title_hits.append(tok)
    title_pts = 0
    if candidate_titles:
        # Full credit at 3 hits — typical PM titles only have ~2-3 unique discriminators.
        title_pts = round(30 * min(1.0, len(title_hits) / 3.0))

    # Seniority match bonus (15 if exact match, 7 if adjacent).
    _ADJACENT = {
        "junior": {"mid"}, "mid": {"junior", "senior"},
        "senior": {"mid", "lead"}, "lead": {"senior", "principal"},
        "principal": {"lead"},
    }
    cand_seniority = ""
    for t in candidate_titles or []:
        for level in ("principal", "lead", "senior", "mid", "junior"):
            if level in (t or "").lower():
                cand_seniority = level
                break
        if cand_seniority:
            break
    seniority_pts = 0
    seniority_note = ""
    if cand_seniority and opp.get("seniority"):
        if cand_seniority == opp["seniority"]:
            seniority_pts = 15
            seniority_note = f"exact seniority match ({cand_seniority})"
        elif opp["seniority"] in _ADJACENT.get(cand_seniority, set()):
            seniority_pts = 7
            seniority_note = f"adjacent seniority ({cand_seniority} ↔ {opp['seniority']})"

    score = min(100, skill_pts + title_pts + seniority_pts)

    # Build human-readable rationale for the report.
    parts: list[str] = []
    if skill_hits:
        sample = ", ".join(skill_hits[:6])
        more = "…" if len(skill_hits) > 6 else ""
        parts.append(f"matches {len(skill_hits)} candidate skill"
                     f"{'s' if len(skill_hits)!=1 else ''} ({sample}{more}) → +{skill_pts}")
    if title_hits:
        parts.append(f"role-title overlap on `{', '.join(title_hits[:4])}` → +{title_pts}")
    if seniority_note:
        parts.append(f"{seniority_note} → +{seniority_pts}")
    rationale = ("; ".join(parts) + ".") if parts else ""
    return score, rationale


from src.company import (
    KNOWN_CR_COMPANIES as _KNOWN_CR_COMPANIES,
    resolve_company_domain as _resolve_company_domain,
)


def _load_cr_companies_from_env() -> list[dict]:
    """Parse the CR_COMPANIES env var into a list of {name, domain} dicts.

    Format: comma-separated. Each entry is either:
        - "CompanyName"           (resolved via built-in registry)
        - "CompanyName:domain.com" (explicit override)
    Unknown names are skipped with a warning.
    """
    raw = os.getenv("CR_COMPANIES", "").strip()
    if not raw:
        return []

    out: list[dict] = []
    unresolved: list[str] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            name, domain = entry.split(":", 1)
            name = name.strip()
            domain = domain.strip()
        else:
            name = entry
            domain = _resolve_company_domain(name) or ""
        if not domain:
            unresolved.append(name)
            continue
        out.append({"name": name, "domain": domain})

    if unresolved:
        _warn(f"CR_COMPANIES — no careers domain registered for: "
              f"{', '.join(unresolved)} (use 'Name:domain.com' format to override).")
    return out


def _classify_company_url(url: str, host: str) -> str:
    """Classify a company-search URL as `direct_listing` or `search_url`.
    Careers homepages / index pages get `search_url` (deep-link style),
    so the user knows it's a starting point not a specific posting."""
    if not url:
        return "search_url"
    # Strip query/fragment for path analysis.
    path = url.split("?")[0].split("#")[0]
    # If path is empty (just host) or a known index name → search_url.
    after_host = path.split(host, 1)[-1].rstrip("/")
    if not after_host or after_host.lower() in (
        "/jobs", "/careers", "/career", "/employment", "/work-with-us",
        "/join-us", "/positions", "/openings", "/opportunities",
    ):
        return "search_url"
    # PDFs / docs are clearly not job postings — drop later.
    if path.lower().endswith((".pdf", ".doc", ".docx", ".ppt", ".pptx")):
        return "non_job_doc"
    return "direct_listing"


def _search_company_careers_via_serper(
    companies: list[dict],
    role_keywords: list[str],
    location: str,
    max_per_company: int = 3,
) -> list[dict]:
    """Use Serper's Google Jobs vertical to find specific job postings at each
    company. Google Jobs integrates with most ATSes (Workday, Greenhouse,
    Lever, etc.) so this surfaces real openings rather than careers indexes."""
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key or not companies or not role_keywords:
        return []

    try:
        import requests
    except ImportError:
        return []

    out: list[dict] = []
    # Compose: "<role kw> <company name>" — Google Jobs filters company well.
    primary_kw = role_keywords[0].strip() if role_keywords else ""
    if not primary_kw:
        return []

    # Probe once: if Serper Jobs endpoint isn't available on this account
    # (404 → not on this plan) bail out quietly instead of warning per-company.
    serper_jobs_disabled = False

    for company in companies:
        if serper_jobs_disabled:
            break
        name = company["name"]
        query = f"{primary_kw} {name}"
        try:
            resp = requests.post(
                "https://google.serper.dev/jobs",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "location": location, "num": max_per_company},
                timeout=15,
            )
            if resp.status_code == 404:
                # Endpoint not enabled on this Serper plan — skip silently.
                _info("Serper Google Jobs endpoint unavailable on this account; "
                      "company-careers search will use Tavily only.")
                serper_jobs_disabled = True
                continue
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            _warn(f"Serper Google Jobs search for {name} failed: {e}")
            continue

        for item in data.get("jobs", []) or []:
            url = item.get("link") or item.get("share_link") or ""
            company_name_in_result = (item.get("company") or "").lower()
            # Confirm the result is actually from THIS company (not just text match).
            if name.lower() not in company_name_in_result and \
               name.lower() not in url.lower() and \
               name.lower() not in (item.get("title", "")).lower():
                continue
            out.append({
                "title": item.get("title", "") or f"{name} role",
                "company": item.get("company") or name,
                "location": item.get("location") or location,
                "modality": None,
                "snippet": (item.get("description") or "")[:400],
                "url": url,
                "source": _slugify(name, max_len=20).lower() or "company_careers",
                "link_type": "direct_listing",
                "via": "company_careers_search:serper",
                "seniority": None,
            })

    return out


def _search_company_careers_via_tavily(
    companies: list[dict],
    role_keywords: list[str],
    location: str,
    max_per_company: int = 3,
) -> list[dict]:
    """For each company, run a Tavily site:-filtered search for jobs matching
    the role keywords. Returns direct_listing opportunities to feed into the
    existing enrichment pipeline (Tavily extract + match scoring).
    Careers homepages / index pages are tagged as `search_url`.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key or not companies or not role_keywords:
        return []

    try:
        import requests
    except ImportError:
        return []

    kw_phrase = " OR ".join(f'"{k.strip()}"' for k in role_keywords[:3] if k.strip())
    if not kw_phrase:
        return []

    # Reuse the module-level kill-switch from extract — once Tavily returns
    # a quota error, both /search and /extract are gated by the same plan.
    global _TAVILY_QUOTA_EXHAUSTED
    if _TAVILY_QUOTA_EXHAUSTED:
        _info("Skipping Tavily company-careers search — Tavily quota already "
              "exhausted earlier in this run.")
        return []

    out: list[dict] = []
    for company in companies:
        if _TAVILY_QUOTA_EXHAUSTED:
            break
        domain = company["domain"]
        name = company["name"]
        if "/" in domain:
            host, path = domain.split("/", 1)
            inurl_part = f' inurl:"{path}"'
        else:
            host = domain
            inurl_part = ""
        # Boost in-country hits with location synonyms when the target is CR.
        loc_query = location
        if location.lower().strip() in ("costa rica", "costa-rica", "cr"):
            loc_query = '("Costa Rica" OR "San José" OR Heredia OR Cartago OR Alajuela)'
        query = (f"({kw_phrase}) (job OR career OR position OR hiring) "
                 f"site:{host}{inurl_part} {loc_query}")
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_per_company,
                    "search_depth": "basic",
                },
                timeout=20,
            )
            # Detect quota / rate-limit error and stop hammering the API.
            if resp.status_code in (429, 432):
                _warn(f"Tavily quota / rate limit reached (status "
                      f"{resp.status_code}) at {name}. Skipping remaining "
                      f"{len(companies) - companies.index(company) - 1} "
                      "company-careers search(es) and falling back to "
                      "Serper-only for the rest of this run.")
                _TAVILY_QUOTA_EXHAUSTED = True
                break
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            _warn(f"Tavily search for {name} failed: {e}")
            continue

        for item in data.get("results", []):
            url = item.get("url", "")
            if not url:
                continue
            link_type = _classify_company_url(url, host)
            if link_type == "non_job_doc":
                continue   # drop PDFs / docs
            out.append({
                "title": (item.get("title") or "").strip() or f"{name} role",
                "company": name,
                "location": location,
                "modality": None,
                "snippet": (item.get("content") or "")[:400],
                "url": url,
                "source": _slugify(name, max_len=20).lower() or "company_careers",
                "link_type": link_type,
                "via": "company_careers_search:tavily",
                "seniority": None,
            })

    return out


def _search_company_careers(
    companies: list[dict],
    role_keywords: list[str],
    location: str,
    max_per_company: int = 3,
) -> list[dict]:
    """Combine Serper Google Jobs (specific postings) + Tavily site: search
    (careers indexes / fallback). Dedupes by URL."""
    serper_results = _search_company_careers_via_serper(
        companies, role_keywords, location, max_per_company)
    tavily_results = _search_company_careers_via_tavily(
        companies, role_keywords, location, max_per_company)

    seen: set = set()
    merged: list[dict] = []
    # Serper first — tends to be higher-quality direct listings.
    for r in serper_results + tavily_results:
        u = r.get("url")
        if u and u not in seen:
            seen.add(u)
            merged.append(r)
    return merged


# ──────────────────────────────────────────────────────────────────────────────
# Direct job-posting URL patterns — used to extract individual job URLs from
# listing/aggregator pages and to validate that Serper organic results are
# real postings (not company landing pages or articles).
# ──────────────────────────────────────────────────────────────────────────────
_DIRECT_JOB_URL_PATTERNS = [
    # LinkedIn specific job posting
    re.compile(r"https?://[^\s\"'<>)]*linkedin\.com/jobs/view/\d+[^\s\"'<>)]*", re.I),
    # Jobgether single offer
    re.compile(r"https?://[^\s\"'<>)]*jobgether\.com/offer/[a-z0-9-]+", re.I),
    # Wellfound (formerly AngelList Talent)
    re.compile(r"https?://[^\s\"'<>)]*wellfound\.com/jobs/\d+[^\s\"'<>)]*", re.I),
    # Greenhouse (and boards.greenhouse.io)
    re.compile(r"https?://[^\s\"'<>)]*greenhouse\.io/[^/\s]+/jobs/\d+[^\s\"'<>)]*", re.I),
    # Lever
    re.compile(r"https?://[^\s\"'<>)]*jobs\.lever\.co/[^/\s]+/[a-f0-9-]{8,}[^\s\"'<>)]*", re.I),
    # Ashby
    re.compile(r"https?://[^\s\"'<>)]*jobs\.ashbyhq\.com/[^/\s]+/[a-f0-9-]{8,}[^\s\"'<>)]*", re.I),
    # Workday (any tenant)
    re.compile(r"https?://[^\s\"'<>)]*\.myworkdayjobs\.com/[^/\s]+/job/[^\s\"'<>)]+", re.I),
    # RemoteOK
    re.compile(r"https?://[^\s\"'<>)]*remoteok\.com/remote-jobs/\d+[^\s\"'<>)]*", re.I),
    # WeWorkRemotely
    re.compile(r"https?://[^\s\"'<>)]*weworkremotely\.com/remote-jobs/[a-z0-9-]+", re.I),
    # Amazon Jobs
    re.compile(r"https?://[^\s\"'<>)]*amazon\.jobs/[a-z]+/jobs/\d+[^\s\"'<>)]*", re.I),
    # SmartRecruiters
    re.compile(r"https?://[^\s\"'<>)]*smartrecruiters\.com/[^/\s]+/\d{8,}[^\s\"'<>)]*", re.I),
    # iCIMS (commonly used by F500)
    re.compile(r"https?://[^\s\"'<>)]*\.icims\.com/jobs/\d+/[^\s\"'<>)]+", re.I),
    # Get on Board (LATAM)
    re.compile(r"https?://[^\s\"'<>)]*getonbrd\.com/jobs/[a-z0-9-]+", re.I),
    # GetonBoard alt domain
    re.compile(r"https?://[^\s\"'<>)]*getonboard\.com/jobs/[a-z0-9-]+", re.I),
    # Indeed (specific)
    re.compile(r"https?://[^\s\"'<>)]*indeed\.com/[^\s\"'<>)]*viewjob[^\s\"'<>)]+", re.I),
]


def _extract_job_urls_from_content(content: str, max_urls: int = 25) -> list[str]:
    """Find absolute job-posting URLs inside a Tavily-extracted page body
    (markdown). Returns deduped URLs matching known specific-posting patterns."""
    if not content:
        return []
    found: list[str] = []
    seen: set = set()
    for pat in _DIRECT_JOB_URL_PATTERNS:
        for m in pat.findall(content):
            url = m if isinstance(m, str) else (m[0] if m else "")
            if not url:
                continue
            # Strip trailing punctuation that often gets glued onto URLs.
            url = url.rstrip(").,;:!?\"'>]}")
            if url not in seen:
                seen.add(url)
                found.append(url)
                if len(found) >= max_urls:
                    return found
    return found


def _resolve_listing_urls_to_jobs(
    opportunities: list[dict],
    location_filter: str,
    max_per_listing: int = 10,
) -> list[dict]:
    """For aggregator/listing URLs (e.g. jobgether.com/remote-jobs/...,
    LinkedIn category pages, careers indexes), use Tavily /extract to fetch
    the page, then parse out individual job-posting URLs and add them as
    `direct_listing` opportunities.

    The listing URL itself is kept (still useful as a starting point) but
    the new specific URLs are added so the user gets clickable absolute job
    links in the report.
    """
    if not os.getenv("TAVILY_API_KEY"):
        return opportunities

    # Identify which opportunities are listing/aggregator pages.
    aggregator_idxs: list[int] = []
    for i, o in enumerate(opportunities):
        url = (o.get("url") or "").lower()
        link_type = o.get("link_type", "")
        is_listing = (
            link_type == "search_url"
            # jobgether category pages
            or ("jobgether.com/remote-jobs/" in url and "/offer/" not in url)
            # any URL classified as careers index by _classify_company_url
            or (link_type == "search_url" and any(
                seg in url for seg in ("/careers", "/jobs", "/employment")
            ))
        )
        if is_listing:
            aggregator_idxs.append(i)

    if not aggregator_idxs:
        return opportunities

    listing_urls = [opportunities[i].get("url", "") for i in aggregator_idxs]
    listing_urls = [u for u in listing_urls if u]
    _info(f"Following {len(listing_urls)} listing/aggregator URL(s) to extract "
          "individual job postings …")

    content_map = _tavily_extract_batch(listing_urls)

    # Build a set of URLs already known so we don't add duplicates.
    seen_urls: set = {(o.get("url") or "") for o in opportunities}
    new_jobs: list[dict] = []

    for i in aggregator_idxs:
        agg = opportunities[i]
        agg_url = agg.get("url", "")
        content = content_map.get(agg_url, "")
        if not content:
            continue
        job_urls = _extract_job_urls_from_content(content, max_urls=max_per_listing)
        for ju in job_urls:
            if ju in seen_urls:
                continue
            seen_urls.add(ju)
            new_jobs.append({
                # Title/snippet/etc filled in by the Tavily-enrichment pass.
                "title": "",
                "company": agg.get("company") or "",
                "location": agg.get("location") or location_filter,
                "modality": agg.get("modality"),
                "snippet": "",
                "url": ju,
                "source": _normalize_source_from_url(ju) or "followed",
                "link_type": "direct_listing",
                "via": f"followed_from:{agg.get('source','listing')}",
                "seniority": agg.get("seniority"),
            })

    if new_jobs:
        _ok(f"Extracted {len(new_jobs)} individual job URL(s) from listing pages.")
    else:
        _info("No specific job URLs found in any listing page.")
    return opportunities + new_jobs


def _search_serper_organic(query: str, max_results: int = 10,
                           gl: str = "cr") -> list[dict]:
    """Use Serper's standard Google /search endpoint to find direct job
    posting URLs. Returns opportunities with link_type='direct_listing'."""
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key or not query:
        return []
    try:
        import requests
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results, "gl": gl, "hl": "en"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        _warn(f"Serper organic search failed: {e}")
        return []

    out: list[dict] = []
    for item in (data.get("organic") or []):
        url = item.get("link") or ""
        if not url:
            continue
        # Only keep results matching a known direct-job-posting pattern.
        is_direct = any(p.search(url) for p in _DIRECT_JOB_URL_PATTERNS)
        out.append({
            "title": item.get("title", "") or "",
            "company": "(see posting)",
            "location": "Costa Rica",
            "modality": None,
            "snippet": (item.get("snippet") or "")[:400],
            "url": url,
            "source": _normalize_source_from_url(url) or "serper_organic",
            "link_type": "direct_listing" if is_direct else "search_url",
            "via": "serper_organic",
        })
    return out


# Module-level kill-switch: once Tavily returns a quota/rate-limit error
# (432 / 429), STOP making further extract calls in this run. Saves time
# and avoids spamming warnings.
_TAVILY_QUOTA_EXHAUSTED = False


def _tavily_extract_batch(urls: list[str]) -> dict[str, str]:
    """Call Tavily's /extract endpoint for a batch of URLs. Returns
    {url: raw_content} for successful extractions; missing keys = failed.

    Sets the module-level kill-switch on 432/429 so subsequent calls are
    short-circuited (Tavily free/dev quotas are easy to hit).
    """
    global _TAVILY_QUOTA_EXHAUSTED
    if _TAVILY_QUOTA_EXHAUSTED:
        return {}
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key or not urls:
        return {}
    try:
        import requests
        resp = requests.post(
            "https://api.tavily.com/extract",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"urls": urls, "extract_depth": "basic"},
            timeout=60,
        )
        if resp.status_code in (429, 432):
            if not _TAVILY_QUOTA_EXHAUSTED:
                _warn("Tavily extract quota / rate limit reached "
                      f"(status {resp.status_code}). Keeping Serper search "
                      "snippets as descriptions and skipping further extracts.")
            _TAVILY_QUOTA_EXHAUSTED = True
            return {}
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        _warn(f"Tavily extract batch failed: {e}")
        return {}

    out: dict[str, str] = {}
    for r in data.get("results", []) or []:
        url = r.get("url") or ""
        content = r.get("raw_content") or ""
        if url and content:
            out[url] = content
    return out


def _enrich_listings_via_tavily(
    opportunities: list[dict],
    candidate_skills: list[str] | None = None,
    candidate_titles: list[str] | None = None,
    location_filter: str = "",
    allow_remote: bool = True,
) -> list[dict]:
    """For each direct_listing, fetch content via Tavily /extract and:
       • normalize `source` from the URL (e.g. jobgether.com → "jobgether")
       • populate a richer description (snippet) from the page content
       • parse table fields: modality, contract_type, seniority,
         experience_years, salary_hint, tech_stack, requirements_summary,
         responsibilities, benefits
       • compute match_score + why_relevant from candidate skills/titles
       • drop entries that are login-walled, expired, or fail extraction
       • drop LinkedIn category-aggregator URLs (search-result pages)
       • drop postings whose body doesn't mention the target location or
         (when allowed) any remote-friendly indicator
    Search-URL deep-links are passed through unchanged.
    Falls back to the legacy availability check when TAVILY_API_KEY is unset.
    """
    if not os.getenv("TAVILY_API_KEY"):
        return opportunities  # caller will run legacy availability check

    candidate_skills = candidate_skills or []
    candidate_titles = candidate_titles or []

    direct = [o for o in opportunities if o.get("link_type") == "direct_listing"]
    others = [o for o in opportunities if o.get("link_type") != "direct_listing"]

    # Pre-filter: drop LinkedIn category aggregator URLs upfront (saves API calls).
    pre_count = len(direct)
    direct = [o for o in direct if not _is_linkedin_category_aggregator(o.get("url", ""))]
    aggregator_dropped = pre_count - len(direct)
    if aggregator_dropped:
        _info(f"Dropped {aggregator_dropped} LinkedIn category aggregator URL(s) "
              "(search-result pages, not single jobs).")

    if not direct:
        return others

    # Prioritize URLs that match a known direct-job-posting pattern — those
    # are most likely to yield real, specific job content. Lower-confidence
    # URLs (careers indexes, aggregator pages without /offer/, etc.) go last
    # and get capped to stay within Tavily extract quotas.
    def _url_quality(opp: dict) -> int:
        url = opp.get("url") or ""
        if any(p.search(url) for p in _DIRECT_JOB_URL_PATTERNS):
            return 0   # highest priority: matches a specific posting pattern
        return 1
    direct.sort(key=_url_quality)

    # Hard cap on Tavily extract calls per run — protects against rate
    # limits on free/dev plans. Configurable via TAVILY_EXTRACT_BUDGET.
    try:
        budget = int(os.getenv("TAVILY_EXTRACT_BUDGET", "100"))
    except ValueError:
        budget = 100
    if len(direct) > budget:
        _info(f"Capping Tavily extracts at {budget} (set TAVILY_EXTRACT_BUDGET "
              f"to override; got {len(direct)} candidates) — taking the "
              "highest-confidence URLs first.")
        # Move overflow into `others` as `search_url` so they still appear
        # in Category 2 of the report instead of being silently lost.
        for opp in direct[budget:]:
            opp["link_type"] = "search_url"
            opp["snippet"] = opp.get("snippet") or "(not extracted — quota cap)"
            others.append(opp)
        direct = direct[:budget]

    _info(f"Extracting page content for {len(direct)} direct listing(s) via Tavily …")

    BATCH = 20
    enriched: list[dict] = []
    walled = 0
    expired = 0
    failed = 0
    wrong_location = 0
    redirected = 0
    stale = 0

    for start in range(0, len(direct), BATCH):
        batch = direct[start:start + BATCH]
        urls = [o.get("url", "") for o in batch if o.get("url")]
        content_map = _tavily_extract_batch(urls)

        for opp in batch:
            url = opp.get("url", "")
            content = content_map.get(url, "")
            # Fall back to the existing snippet (e.g. from Serper organic
            # search) when Tavily extract didn't return content — Serper's
            # snippet is short but usually enough for validation + scoring.
            fell_back = False
            if not content:
                content = (opp.get("snippet") or "").strip()
                fell_back = bool(content)

            if not content:
                failed += 1
                continue
            # Login-wall check only on full Tavily extracts. Search-engine
            # snippets are short by definition; the `< 200 chars` rule would
            # produce false positives.
            if not fell_back and _is_login_walled(content):
                walled += 1
                continue
            lower = content.lower()
            if any(phrase in lower for phrase in _CLOSED_PHRASES):
                expired += 1
                continue

            # Slug validation — drops listings that 302-redirected to a
            # generic careers index (the extracted content's body must
            # contain tokens from the original URL's job slug). When we
            # only have the search snippet (limited), be more lenient.
            slug_threshold = 0.25 if fell_back else 0.4
            if not _content_matches_url_slug(content, url, slug_threshold):
                redirected += 1
                continue

            # Staleness — drops postings older than 6 months even when
            # the URL still resolves. Old postings are usually filled.
            if _is_stale_listing(content):
                stale += 1
                continue

            # Location validation — only enforce when a location filter is
            # supplied. Drops foreign-country postings that the search returned.
            if location_filter:
                if not _is_location_relevant(content, location_filter,
                                              allow_remote=allow_remote):
                    wrong_location += 1
                    continue

            # Enrich the opportunity in place.
            opp["available"] = True
            opp["accepting_applications"] = True
            normalized = _normalize_source_from_url(url)
            if normalized:
                opp["source"] = normalized

            # Use full Tavily content when available; otherwise keep the
            # search-engine snippet (already in opp["snippet"]).
            if not fell_back:
                opp["snippet"] = _summarize_extracted_content(content, max_chars=1200)

            parsed = _parse_job_fields_from_content(content, title=opp.get("title", ""))
            for key, value in parsed.items():
                # Only fill fields the agent didn't already populate or are empty.
                existing = opp.get(key)
                if existing in (None, "", []) or (key == "tech_stack" and not existing):
                    opp[key] = value

            # Match score + rationale based on candidate profile.
            score, rationale = _compute_match_score(opp, candidate_skills, candidate_titles)
            if score > (opp.get("match_score") or 0):
                opp["match_score"] = score
            if rationale and not opp.get("why_relevant"):
                opp["why_relevant"] = rationale

            enriched.append(opp)

    if walled:
        _info(f"Skipped {walled} login-walled listing(s).")
    if expired:
        _info(f"Skipped {expired} expired/closed listing(s).")
    if redirected:
        _info(f"Skipped {redirected} listing(s) where the URL redirected "
              "to an unrelated page (slug mismatch).")
    if stale:
        _info(f"Skipped {stale} stale listing(s) (≥ 6 months old).")
    if wrong_location:
        _info(f"Skipped {wrong_location} listing(s) outside target location "
              f"({location_filter}{' / remote' if allow_remote else ''}).")
    if failed:
        _info(f"Skipped {failed} listing(s) that could not be extracted.")

    return others + enriched


def _check_url_available(url: str) -> dict:
    """HEAD + GET request to verify a job listing URL is live and still accepting applications.

    Returns:
        available  (bool)       — URL is reachable (2xx/3xx)
        accepting  (bool|None)  — True = open, False = "no longer accepting", None = couldn't determine
    """
    if not url:
        return {"available": False, "accepting": None}
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (cv-optimizer job availability check)"}
        resp = requests.head(url, allow_redirects=True, timeout=6, headers=headers)
        if resp.status_code >= 400:
            return {"available": False, "accepting": None}
        try:
            get_resp = requests.get(url, allow_redirects=True, timeout=10, headers=headers)
            content = get_resp.text.lower()
            for phrase in _CLOSED_PHRASES:
                if phrase in content:
                    return {"available": True, "accepting": False}
        except Exception:
            pass
        return {"available": True, "accepting": True}
    except Exception:
        return {"available": False, "accepting": None}


def _derive_role_keywords_from_profile(profile: dict) -> list[str]:
    """Derive SHORT role keywords (3-5 tokens each) from a parsed CV profile.

    Pulls from `work_experience_summary` (format "Title @ Company (date – date)")
    and trims each title to a clean short form, e.g.
    "Senior Project Manager - Public Relations & Marketing" → "Senior Project Manager".
    Search engines work much better with short, focused queries.
    """
    if not profile:
        return []

    raw_titles: list[str] = []
    for entry in (profile.get("work_experience_summary") or [])[:4]:
        if not isinstance(entry, str):
            continue
        title_part = entry.split(" @ ")[0].split(" - ")[0].strip()
        if title_part:
            raw_titles.append(title_part)

    headline = (profile.get("headline") or "").strip()
    if headline:
        raw_titles.append(headline)

    # Trim each title to its first clause (cut on dashes, slashes, "and", commas).
    cleaned: list[str] = []
    for t in raw_titles:
        # Split on common separators and keep only the first segment.
        first = re.split(r"\s*[-–/&,|]\s*|\s+and\s+|\s+for\s+", t, maxsplit=1)[0].strip()
        # Cap to 5 words (search-friendly).
        words = first.split()
        if words:
            cleaned.append(" ".join(words[:5]))

    # Dedup case-insensitively while preserving order.
    seen: set = set()
    out: list[str] = []
    for t in cleaned:
        key = re.sub(r"\s+", " ", t).lower()
        if key and key not in seen:
            seen.add(key)
            out.append(t)
    return out[:5]


def _extract_cv_profile_for_report(cv_path: Path) -> dict:
    """Parse the CV and extract structured profile fields for report enrichment.
    Makes one lightweight Haiku call. Returns {} on any failure."""
    import json as _json
    try:
        from src.tools import parse_cv as _parse_cv
        # parse_cv is a CrewAI @tool — must call its underlying .func to invoke directly.
        cv_raw = _json.loads(_parse_cv.func(str(cv_path)))
        if "error" in cv_raw:
            return {}
        paragraphs = cv_raw.get("paragraphs", [])
        full_text = "\n".join(p.get("text", "") for p in paragraphs).strip()
        if not full_text:
            return {}
    except Exception as e:
        _warn(f"CV profile extraction failed in parse_cv: {e}")
        return {}

    try:
        from src.llm.client import get_default_client
        from src.settings import get_settings as _gs
        _llm = get_default_client()
        prompt = (
            "Extract from the CV text below and return ONLY a valid JSON object with these keys "
            "(use null or empty list for missing fields):\n"
            "  full_name (str), headline (str|null), summary (str|null),\n"
            "  skills (list[str] — up to 20 key skills),\n"
            "  certifications (list[str]),\n"
            "  languages (list[str]),\n"
            "  work_experience_summary (list[str] — one entry per role: "
            "'Job Title @ Company (Start – End)').\n\n"
            f"CV text:\n{full_text[:8000]}"
        )
        content = _llm.complete(
            model=_gs().model_haiku,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        ).strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
        return _json.loads(content)
    except Exception:
        return {}


def _write_opportunity_report(opp: dict, report_dir: Path, index: int) -> Path:
    """Write a self-contained PDF report for one job opportunity."""
    title_slug = _slugify(opp.get("title", "unknown"))
    company_slug = _slugify(opp.get("company", "unknown"), max_len=20)
    filename = f"{index:02d}_{title_slug}__{company_slug}.pdf"
    filepath = report_dir / filename

    def _row(label: str, value) -> str:
        return f"| **{label}** | {value or '—'} |"

    available = opp.get("available")
    accepting = opp.get("accepting_applications")

    title = opp.get("title", "Unknown Role")
    if available is False:
        title_display = f"~~{title}~~ *(listing unavailable)*"
        status_md = "❌ Unavailable (dead URL)"
    elif accepting is False:
        title_display = f"~~{title}~~ *(no longer accepting applications)*"
        status_md = "🚫 No longer accepting applications"
    elif available is True and accepting is True:
        title_display = title
        status_md = "✅ Open — accepting applications"
    elif available is True:
        title_display = title
        status_md = "✅ URL live (application status not verified)"
    else:
        title_display = title
        status_md = "— (not checked)"

    lines = [
        f"# {title_display}",
        "",
        "## Overview",
        "",
        "| Field | Value |",
        "| --- | --- |",
        _row("Company", opp.get("company")),
        _row("Status", status_md),
        _row("Location", opp.get("location")),
        _row("Modality", opp.get("modality")),
        _row("Contract", opp.get("contract_type")),
        _row("Seniority", opp.get("seniority")),
        _row("Experience", opp.get("experience_years")),
        _row("Salary", opp.get("salary_hint")),
        _row("Posted", opp.get("posted_date")),
        _row("Deadline", opp.get("application_deadline")),
        _row("Source", f"`{opp.get('source', '?')}`"),
        _row("Job ID", opp.get("job_id")),
        "",
        "## Links",
        "",
        f"- **Listing URL:** {opp.get('url', '—')}",
    ]
    if opp.get("apply_url") and opp["apply_url"] != opp.get("url"):
        lines.append(f"- **Apply URL:** {opp['apply_url']}")
    lines += [
        "",
        "## Match Analysis",
        "",
        f"**Score:** {opp.get('match_score', 0)}/100",
    ]
    if opp.get("why_relevant"):
        lines += ["", opp["why_relevant"]]
    if opp.get("snippet"):
        lines += ["", "## Description", "", opp["snippet"]]
    if opp.get("requirements_summary"):
        lines += ["", "## Key Requirements", ""]
        for req in opp["requirements_summary"]:
            lines.append(f"- {req}")
    if opp.get("tech_stack"):
        lines += ["", "## Tech Stack", ""]
        lines.append(", ".join(f"`{t}`" for t in opp["tech_stack"]))
    if opp.get("benefits"):
        lines += ["", "## Benefits", "", opp["benefits"]]

    md_text = "\n".join(lines) + "\n"
    try:
        from src.pdf_renderer import write_pdf_from_markdown
        write_pdf_from_markdown(md_text, filepath)
    except Exception as pdf_e:
        _warn(f"Could not render opportunity PDF ({filepath.name}), "
              f"falling back to .md: {pdf_e}")
        filepath = filepath.with_suffix(".md")
        filepath.write_text(md_text, encoding="utf-8")
    return filepath


def _write_search_summary_report(data: dict, output_dir: Path,
                                   candidate_name: str = "",
                                   profile_data: dict | None = None) -> Path:
    """Write a comprehensive candidate-profile + all-opportunities markdown report.

    Sections:
      1. Candidate Profile (rich, with summary / skills / work history if profile_data provided)
      2. Search Configuration (which API is active)
      3. Search Summary (stats + queries)
      4. Recommendations (top matches, tips)
      5. Category 1 — Direct Job Listings
      6. Category 2 — Job Board Search Links

    Always written, even when 0 opportunities are found.
    """
    import datetime as _dt
    now = _dt.datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M (local time)")

    report_path = output_dir / "job_search_report.pdf"

    pd = profile_data or {}
    name = pd.get("full_name") or data.get("candidate_name") or candidate_name or "*(parsed from CV)*"
    headline = pd.get("headline") or data.get("candidate_headline")
    summary_text = pd.get("summary")
    skills: list[str] = pd.get("skills") or []
    certs: list[str] = pd.get("certifications") or []
    languages_list: list[str] = pd.get("languages") or []
    work_history: list[str] = pd.get("work_experience_summary") or []

    all_opps = data.get("opportunities", [])
    direct_listings = [o for o in all_opps if o.get("link_type") == "direct_listing"]
    search_links = [o for o in all_opps if o.get("link_type") != "direct_listing"]

    from collections import Counter as _Counter
    seniority_counts = _Counter(
        o.get("seniority") or "unspecified" for o in all_opps if o.get("seniority")
    )
    seniority_breakdown = ", ".join(
        f"{lvl}: {cnt}" for lvl, cnt in sorted(
            seniority_counts.items(),
            key=lambda x: _SENIORITY_ORDER.index(x[0]) if x[0] in _SENIORITY_ORDER else 99,
        )
    ) if seniority_counts else "—"

    sources_used: list[str] = data.get("sources_used", [])
    if "tavily" in sources_used:
        api_status = "✅ **Tavily** — live web search (direct job posting URLs)"
    elif any(s in sources_used for s in ("serper", "serper_jobs")):
        api_status = "✅ **Serper / Google Jobs** — live search (direct job posting URLs)"
    else:
        api_status = ("⚠️ **None** — only pre-built deep-link search URLs returned. "
                      "Set `TAVILY_API_KEY` or `SERPER_API_KEY` in `.env` for live results.")

    unavailable_count = sum(
        1 for o in direct_listings
        if o.get("available") is False or o.get("accepting_applications") is False
    )
    top_matches = sorted(
        [o for o in direct_listings if o.get("match_score", 0) > 0],
        key=lambda o: o.get("match_score", 0),
        reverse=True,
    )[:3]

    lines: list[str] = [
        "# Job Search Report",
        "",
        f"*Generated: {timestamp}*",
        "",
        "---",
        "",
        "## Candidate Profile",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| **Name** | {name} |",
    ]
    if headline:
        lines.append(f"| **Headline** | {headline} |")
    if data.get("cv_source"):
        lines.append(f"| **CV file** | `{data['cv_source']}` |")
    lines += [
        f"| **Target location** | {data.get('location_filter') or '—'} |",
        f"| **Seniority** | {data.get('seniority_filter') or '—'} |",
        f"| **Modality** | {data.get('modality_filter') or '—'} |",
    ]
    if data.get("role_keywords"):
        lines.append(f"| **Role keywords** | {', '.join(data['role_keywords'])} |")
    if data.get("keywords_filter"):
        lines.append(f"| **Extra keywords** | {', '.join(data['keywords_filter'])} |")
    lines.append("")

    if summary_text:
        lines += ["### Professional Summary", "", summary_text, ""]

    if work_history:
        lines += ["### Work History", ""]
        for entry in work_history:
            lines.append(f"- {entry}")
        lines.append("")

    if skills:
        lines += ["### Skills", "", ", ".join(f"`{s}`" for s in skills), ""]

    if certs:
        lines += ["### Certifications", ""]
        for cert in certs:
            lines.append(f"- {cert}")
        lines.append("")

    if languages_list:
        lines += ["### Languages", "", ", ".join(languages_list), ""]

    # ── Search Configuration ──────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## Search Configuration",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| **Search API** | {api_status} |",
        f"| **Deep-link fallbacks** | {'✅ Included' if 'deep_links' in sources_used else '—'} |",
        f"| **Sources used** | {', '.join(f'`{s}`' for s in sources_used) or '—'} |",
        f"| **Run timestamp** | {data.get('search_timestamp', timestamp)} |",
        "",
    ]

    # ── Search Summary ────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## Search Summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| **Total results** | {len(all_opps)} |",
        f"| **Direct listings (verified URLs)** | {len(direct_listings)} |",
    ]
    if direct_listings:
        lines.append(f"| **Unavailable / closed** | {unavailable_count} |")
    lines += [
        f"| **Job board search links** | {len(search_links)} |",
        f"| **By seniority level** | {seniority_breakdown} |",
        "",
    ]

    if data.get("search_queries_used"):
        lines += ["### Queries Used", ""]
        for q in data["search_queries_used"]:
            lines.append(f"- `{q}`")
        lines.append("")

    # ── Recommendations ───────────────────────────────────────────────────
    lines += ["---", "", "## Recommendations", ""]

    if top_matches:
        lines += ["### Top Matches by Score", ""]
        for opp in top_matches:
            score = opp.get("match_score", 0)
            title = opp.get("title", "Unknown")
            company = opp.get("company", "?")
            url = opp.get("url", "")
            closed = (opp.get("available") is False or opp.get("accepting_applications") is False)
            suffix = " ~~(closed)~~" if closed else ""
            lines.append(f"- **{score}/100** — [{title} @ {company}]({url}){suffix}")
        lines.append("")

    if not any(s in sources_used for s in ("tavily", "serper", "serper_jobs")):
        lines += [
            "### Improve Your Search Results",
            "",
            "No live search API is configured — you are seeing pre-built deep-link search URLs "
            "only, not specific job postings. To receive direct job posting results:",
            "",
            "1. Sign up for a free **Tavily** account: <https://tavily.com> *(recommended)*",
            "2. Add `TAVILY_API_KEY=tvly-xxxxx` to your `.env` file",
            "3. Re-run the search command",
            "",
        ]

    if unavailable_count > 0:
        lines += [
            "### Closed / Unavailable Listings",
            "",
            f"{unavailable_count} listing(s) were found to be unavailable or no longer accepting "
            "applications. They are marked with ~~strikethrough~~ in the listings below. "
            "Focus your applications on the listings marked ✅.",
            "",
        ]

    # ── Category 1: Direct Listings ───────────────────────────────────────
    lines += ["---", "", "## Category 1 — Direct Job Listings", ""]

    if not direct_listings:
        lines += [
            "> No direct job listings were found for this search.",
            "",
            "Direct listings appear here when a live search API (Tavily or Serper) is configured "
            "in `.env` and returns specific job posting URLs.",
            "",
        ]
    else:
        sorted_direct = sorted(direct_listings, key=lambda o: o.get("match_score", 0), reverse=True)
        lines.append(f"*{len(sorted_direct)} listing(s), sorted by match score. "
                     "Unavailable or closed listings are marked ~~like this~~.*")
        lines.append("")
        for i, opp in enumerate(sorted_direct, 1):
            score = opp.get("match_score", 0)
            bar = "█" * (score // 10) + "░" * (10 - score // 10)
            url = opp.get("url", "")
            apply_url = opp.get("apply_url")
            available = opp.get("available")
            accepting = opp.get("accepting_applications")

            title_md = opp.get("title", "Unknown Role")
            if available is False:
                title_md = f"~~{title_md}~~ *(listing unavailable)*"
                status_badge = "❌ Unavailable (dead URL)"
            elif accepting is False:
                title_md = f"~~{title_md}~~ *(no longer accepting applications)*"
                status_badge = "🚫 No longer accepting"
            elif available is True and accepting is True:
                status_badge = "✅ Open"
            else:
                status_badge = "— (not checked)"

            lines += [
                f"### {i}. {title_md} — {opp.get('company', '?')}",
                "",
                f"**Match score:** `{score}/100` {bar}",
                "",
                "| Field | Value |",
                "| --- | --- |",
                f"| Source | `{opp.get('source', '?')}` |",
                f"| Status | {status_badge} |",
                f"| Seniority | {opp.get('seniority') or '—'} |",
                f"| Location | {opp.get('location') or '—'} |",
                f"| Modality | {opp.get('modality') or '—'} |",
                f"| Contract | {opp.get('contract_type') or '—'} |",
                f"| Experience | {opp.get('experience_years') or '—'} |",
                f"| Salary | {opp.get('salary_hint') or '—'} |",
                f"| Posted | {opp.get('posted_date') or '—'} |",
                f"| Deadline | {opp.get('application_deadline') or '—'} |",
                f"| Job ID | {opp.get('job_id') or '—'} |",
                f"| URL | [{url}]({url}) |",
            ]
            if apply_url and apply_url != url:
                lines.append(f"| Apply URL | [{apply_url}]({apply_url}) |")
            lines.append("")
            if opp.get("why_relevant"):
                lines += [f"**Why relevant:** {opp['why_relevant']}", ""]
            if opp.get("snippet"):
                lines += ["**Description:**", "", f"> {opp['snippet']}", ""]
            if opp.get("requirements_summary"):
                lines += ["**Key requirements:**", ""]
                for req in opp["requirements_summary"]:
                    lines.append(f"- {req}")
                lines.append("")
            if opp.get("tech_stack"):
                lines += [f"**Tech stack:** {', '.join(f'`{t}`' for t in opp['tech_stack'])}", ""]
            if opp.get("benefits"):
                lines += [f"**Benefits:** {opp['benefits']}", ""]
            lines += ["---", ""]

    # ── Category 2: Job Board Search Links ────────────────────────────────
    lines += ["## Category 2 — Job Board Search Links", ""]

    if not search_links:
        lines += ["> No job board search links were generated.", ""]
    else:
        lines.append(f"*{len(search_links)} pre-built search URL(s) — click to open the job board "
                     "filtered for your profile.*")
        lines.append("")
        for i, opp in enumerate(search_links, 1):
            url = opp.get("url", "")
            lines += [
                f"### {i}. {opp.get('title', 'Search Link')}",
                "",
                "| Field | Value |",
                "| --- | --- |",
                f"| Board | `{opp.get('source', '?')}` |",
                f"| Seniority | {opp.get('seniority') or '—'} |",
                f"| Location | {opp.get('location') or '—'} |",
                f"| Modality | {opp.get('modality') or '—'} |",
                f"| Search URL | [{url}]({url}) |",
                "",
            ]
            if opp.get("snippet"):
                lines.append(f"*{opp['snippet']}*")
                lines.append("")
            lines.append("---")
            lines.append("")

    md_text = "\n".join(lines)
    try:
        from src.pdf_renderer import write_pdf_from_markdown
        write_pdf_from_markdown(md_text, report_path)
    except Exception as pdf_e:
        _warn(f"Could not render job_search_report.pdf, falling back to .md: {pdf_e}")
        report_path = output_dir / "job_search_report.md"
        report_path.write_text(md_text, encoding="utf-8")
    return report_path


def cmd_search(args: argparse.Namespace) -> int:
    # Skip the interactive wizard if stdin isn't a TTY (e.g. piped input or CI)
    # AND a CV path was passed via --cv. This makes the command scriptable.
    if sys.stdin.isatty() or args.cv is None:
        args = _interactive_search_wizard(args)
        if args is None:
            return 0

    cv_err = _validate_cv_path(args.cv)
    if cv_err:
        _err(cv_err)
        return 2

    if not os.getenv("ANTHROPIC_API_KEY"):
        _err("ANTHROPIC_API_KEY not set in .env or environment")
        return 2

    args.output.mkdir(parents=True, exist_ok=True)

    modality = "remote" if args.remote else (args.modality or "any")
    keywords = [k.strip() for k in args.keywords.split(",")] if args.keywords else []
    include_sources = ([s.strip() for s in args.sources.split(",")]
                       if args.sources else None)
    role_override = ([r.strip() for r in args.role.split(",")]
                     if args.role else None)
    # Quality filters
    exclude_keywords = ([e.strip() for e in args.exclude.split(",")]
                        if getattr(args, "exclude", None) else [])
    max_age_days = getattr(args, "max_age_days", 0) or 0
    exact_location = getattr(args, "exact_location", False)
    # Populated below from the role taxonomy once role keywords are known.
    synonyms_map: dict[str, list[str]] = {}

    _banner(f"JOB SEARCH — based on {args.cv.name}")
    _info(f"Location   : {args.location}")
    _info(f"Modality   : {modality}")
    if args.seniority:
        _info(f"Seniority  : {args.seniority}")
    if args.contract_type:
        _info(f"Contract   : {args.contract_type}")
    if role_override:
        _info(f"Role       : {', '.join(role_override)}")
    if keywords:
        _info(f"Keywords   : {', '.join(keywords)}")
    if include_sources:
        _info(f"Sources    : {', '.join(include_sources)}")
    if args.min_match:
        _info(f"Min match  : {args.min_match}/100")
    _info(f"Max results: {args.max_results}")

    # Both providers are REQUIRED for the search command — they cover
    # complementary surfaces (Tavily: deep-content extract; Serper: Google
    # organic) and the "follow search-URL" feature needs both.
    missing_providers: list[str] = []
    if not os.getenv("TAVILY_API_KEY"):
        missing_providers.append("TAVILY_API_KEY (sign up free at https://tavily.com)")
    if not os.getenv("SERPER_API_KEY"):
        missing_providers.append("SERPER_API_KEY (sign up free at https://serper.dev)")
    if missing_providers:
        _err("The search command requires both providers. Missing:")
        for m in missing_providers:
            _err(f"  • {m}")
        _err("Add the keys to your .env file and re-run.")
        return 2

    from src.search_crew import JobSearchCrew

    levels = _seniority_levels(args.seniority) if args.seniority else []
    levels_str = ", ".join(levels) if levels else ""

    if len(levels) > 1:
        _info(f"Seniority   : {levels[0]} (also including: {', '.join(levels[1:])})")
    elif levels:
        _info(f"Seniority   : {levels[0]}")

    # Extract candidate profile EARLY (one Haiku call) so we can:
    #   • derive fallback role keywords from real job titles
    #   • enrich the final summary report with skills/experience
    _info("Extracting candidate profile from CV …")
    profile_data = _extract_cv_profile_for_report(args.cv) or {}
    cv_titles = _derive_role_keywords_from_profile(profile_data)
    if cv_titles:
        _info(f"Detected role keywords from CV: {', '.join(cv_titles[:5])}")

    # Expand role keywords with recruiter-facing synonyms from the taxonomy.
    try:
        from src.role_taxonomy import expand_keywords
        seed_kw = (role_override or cv_titles or [])[:5]
        synonyms_map = expand_keywords(seed_kw)
        if synonyms_map:
            expanded_count = sum(len(v) for v in synonyms_map.values())
            _info(f"Expanded {len(synonyms_map)} role keyword(s) via taxonomy "
                  f"(+{expanded_count} synonyms).")
    except Exception:
        synonyms_map = {}

    inputs = {
        "cv_docx_path": str(args.cv),
        "location": args.location,
        "modality": modality,
        "seniority": args.seniority or "",
        "seniority_levels": levels_str,
        "max_results": args.max_results,
        "keywords": keywords,
        "contract_type": args.contract_type or "",
        "include_sources": include_sources or [],
        "role_override": role_override or [],
        "max_age_days": max_age_days,
        "exclude_keywords": exclude_keywords,
        "exact_location": exact_location,
        "synonyms": synonyms_map,
    }

    crew_obj = JobSearchCrew(
        location=args.location,
        max_results=args.max_results,
        modality=modality if modality != "any" else None,
        seniority=args.seniority,
        role=args.role,
        keywords=keywords,
        contract_type=args.contract_type,
        include_sources=include_sources,
        min_match=args.min_match,
    ).crew()

    started = time.time()
    result = crew_obj.kickoff(inputs=inputs)

    # Extract result
    try:
        if hasattr(result, "pydantic") and result.pydantic is not None:
            data = result.pydantic.model_dump()
        elif hasattr(result, "raw"):
            data = json.loads(result.raw) if isinstance(result.raw, str) else dict(result.raw)
        else:
            data = {"raw_output": str(result)}
    except Exception:
        data = {"raw_output": str(result)}

    # If parsing landed in raw_output (e.g. crew wrapped JSON in a markdown fence),
    # strip the fence and re-parse so we can access the job data.
    if "raw_output" in data and "opportunities" not in data and "job_opportunities" not in data:
        raw = data["raw_output"]
        raw_stripped = re.sub(r"```(?:json)?\s*\n?", "", raw).strip().rstrip("`").strip()
        # Drop any non-JSON header lines (e.g. "# JobSearchResult") before the object.
        brace = raw_stripped.find("{")
        if brace > 0:
            raw_stripped = raw_stripped[brace:]
        try:
            parsed = json.loads(raw_stripped)
            if isinstance(parsed, dict):
                data.update(parsed)
        except json.JSONDecodeError:
            # Output may be truncated — salvage complete opportunity objects via regex.
            import re as _re
            opp_blobs = _re.findall(r'\{\s*"id"\s*:\s*\d+.*?\}(?=\s*,\s*\{|\s*\])', raw_stripped, _re.DOTALL)
            salvaged: list[dict] = []
            for blob in opp_blobs:
                try:
                    salvaged.append(json.loads(blob))
                except json.JSONDecodeError:
                    pass
            if salvaged:
                _warn(f"Crew output was truncated; salvaged {len(salvaged)} complete opportunity record(s).")
                data["opportunities"] = salvaged
            # Try to recover top-level scalar fields from the partial JSON.
            for field, pattern in [
                ("candidate_name", r'"candidate_name"\s*:\s*"([^"]+)"'),
                ("candidate_email", r'"candidate_email"\s*:\s*"([^"]+)"'),
            ]:
                m = _re.search(pattern, raw_stripped)
                if m:
                    data.setdefault(field, m.group(1))

    # Remap job_opportunities → opportunities (crew output key vs report key)
    if "job_opportunities" in data and "opportunities" not in data:
        data["opportunities"] = data["job_opportunities"]

    # ── Deterministic fallback ───────────────────────────────────────────────
    # If the agent dropped all opportunities (or fabricated unverifiable URLs),
    # call search_jobs directly with the agent-extracted keywords (or sensible
    # defaults derived from CV stem / role override) so the user always gets
    # real, deterministic deep-link search URLs to LinkedIn/Indeed/Glassdoor/etc.
    if not data.get("opportunities"):
        from src.tools import search_jobs as _search_jobs_tool

        agent_keywords = data.get("role_keywords") or []
        # Priority: explicit --role override → agent's keywords → CV-derived
        # titles → user keywords → last-resort generic placeholder.
        fallback_keywords = (role_override or agent_keywords or cv_titles
                             or keywords or ["professional"])

        _info(f"Agent returned no opportunities; running fallback search per "
              f"role keyword: {fallback_keywords[:5]}")

        # Run ONE search per keyword and merge — joining keywords into a single
        # query produces overly-narrow searches that match nothing.
        merged: list[dict] = []
        merged_sources: list[str] = []
        merged_queries: list[str] = []
        seen_urls: set[str] = set()

        for kw in fallback_keywords[:5]:
            tool_input = json.dumps({
                "role_keywords": [kw],
                "location": args.location,
                "seniority": args.seniority or None,
                "seniority_levels": levels_str if levels_str else None,
                "modality": modality if modality != "any" else None,
                "max_results": args.max_results,
                "keywords": keywords,
                "contract_type": args.contract_type or None,
                "include_sources": include_sources,
                "max_age_days": max_age_days,
                "exclude_keywords": exclude_keywords,
                "exact_location": exact_location,
                "synonyms": synonyms_map,
            })
            try:
                tool_data = json.loads(_search_jobs_tool.func(tool_input))
            except Exception as e:
                _warn(f"Fallback search for '{kw}' failed: {e}")
                continue
            for opp in tool_data.get("opportunities", []):
                url = opp.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    merged.append(opp)
            for s in tool_data.get("sources_used", []):
                if s not in merged_sources:
                    merged_sources.append(s)
            merged_queries.extend(tool_data.get("search_queries_used", []))

        try:
            data["opportunities"] = merged
            data.setdefault("total_found", len(merged))
            data.setdefault("sources_used", merged_sources)
            data.setdefault("search_queries_used", merged_queries)
            if not data.get("role_keywords"):
                data["role_keywords"] = fallback_keywords[:5]
            _ok(f"Fallback search returned {len(data['opportunities'])} opportunities.")
        except Exception as e:
            _warn(f"Fallback search_jobs call failed: {e}")

    # If the agent omitted sources_used, infer it from env vars so the report
    # doesn't falsely show "no live search API configured".
    if not data.get("sources_used"):
        inferred: list[str] = []
        if os.getenv("TAVILY_API_KEY"):
            inferred.append("tavily")
        elif os.getenv("SERPER_API_KEY"):
            inferred.append("serper")
        if inferred:
            data["sources_used"] = inferred

    # ── CR transnationals — search each company's careers page ──────────
    # Adds direct-listing opportunities from the curated CR_COMPANIES list.
    # These get processed by the same Tavily-extract enrichment pipeline below.
    cr_companies = _load_cr_companies_from_env()
    if cr_companies:
        _info(f"Searching careers pages of {len(cr_companies)} CR transnational(s) "
              "via Serper Google Jobs + Tavily …")
        co_keywords = (data.get("role_keywords") or cv_titles
                       or role_override or fallback_keywords or ["professional"])
        company_opps = _search_company_careers(
            cr_companies,
            role_keywords=co_keywords,
            location=args.location,
            max_per_company=3,
        )
        if company_opps:
            existing_urls = {o.get("url") for o in data.get("opportunities", [])}
            new_count = 0
            for opp in company_opps:
                if opp.get("url") and opp["url"] not in existing_urls:
                    data.setdefault("opportunities", []).append(opp)
                    existing_urls.add(opp["url"])
                    new_count += 1
            data["total_found"] = len(data["opportunities"])
            srcs = data.setdefault("sources_used", [])
            if "company_careers" not in srcs:
                srcs.append("company_careers")
            _ok(f"Added {new_count} new company-careers opportunit{'y' if new_count == 1 else 'ies'} "
                f"from {len(cr_companies)} CR transnational(s).")
        else:
            _info("No matching openings found on company careers pages.")

    # ── Serper organic Google search — finds direct posting URLs ─────────
    # Runs queries like `"Project Manager" "Costa Rica" site:linkedin.com/jobs/view`
    # to surface specific posting URLs the regular Tavily search may have
    # missed. Each Serper hit either matches a direct-job-URL pattern
    # (→ direct_listing) or is tagged as search_url and then followed below.
    # Use only the top role keyword across a few ATS filters to keep Serper
    # quota usage and downstream Tavily extract budget reasonable.
    serper_role_kws = (data.get("role_keywords") or cv_titles
                       or role_override or fallback_keywords or [])[:1]
    if serper_role_kws:
        _info(f"Querying Serper organic for direct posting URLs "
              f"({len(serper_role_kws)} keyword(s) × 4 ATS filters) …")
        ats_filters = [
            "site:linkedin.com/jobs/view",
            "site:jobgether.com/offer",
            "(site:greenhouse.io OR site:lever.co OR site:ashbyhq.com OR site:myworkdayjobs.com)",
            "(site:wellfound.com/jobs OR site:weworkremotely.com/remote-jobs OR site:smartrecruiters.com)",
        ]
        serper_results: list[dict] = []
        for kw in serper_role_kws:
            for ats in ats_filters:
                q = f'"{kw}" "{args.location}" {ats}'
                serper_results.extend(_search_serper_organic(q, max_results=8, gl="cr"))
        if serper_results:
            existing_urls = {o.get("url") for o in data.get("opportunities", [])}
            added = 0
            for opp in serper_results:
                if opp.get("url") and opp["url"] not in existing_urls:
                    data.setdefault("opportunities", []).append(opp)
                    existing_urls.add(opp["url"])
                    added += 1
            data["total_found"] = len(data["opportunities"])
            srcs = data.setdefault("sources_used", [])
            if "serper_organic" not in srcs:
                srcs.append("serper_organic")
            _ok(f"Added {added} direct-posting URL(s) from Serper organic search.")

    # ── Follow listing/aggregator URLs to extract individual jobs ────────
    # Pages like jobgether.com/remote-jobs/... contain dozens of job links
    # in their markdown — extract each one as its own direct_listing.
    before_follow = len(data.get("opportunities", []))
    data["opportunities"] = _resolve_listing_urls_to_jobs(
        data.get("opportunities", []),
        location_filter=args.location,
        max_per_listing=10,
    )
    if len(data["opportunities"]) != before_follow:
        data["total_found"] = len(data["opportunities"])
        srcs = data.setdefault("sources_used", [])
        if "listing_follow" not in srcs:
            srcs.append("listing_follow")

    # Post-filter by min_match.
    # NOTE: match_score == 0 means "unscored" (the LLM didn't score the item, or
    # the deterministic fallback path was used). Keep unscored items so the user
    # always sees the deep-link search URLs even when --min-match is set.
    opportunities = data.get("opportunities", [])
    if args.min_match:
        opportunities = [
            o for o in opportunities
            if not o.get("match_score") or o.get("match_score", 0) >= args.min_match
        ]
        data["opportunities"] = opportunities
        data["total_found"] = len(opportunities)

    # Stamp search metadata and search parameters so the report always has context
    import datetime
    data.setdefault("search_timestamp", datetime.datetime.utcnow().isoformat() + "Z")
    data.setdefault("cv_source", str(args.cv))
    data.setdefault("location_filter", args.location)
    data.setdefault("seniority_filter", args.seniority or "")
    data.setdefault("modality_filter", modality)
    if keywords:
        data.setdefault("keywords_filter", keywords)
    if role_override:
        existing = data.get("role_keywords") or []
        if not existing:
            data["role_keywords"] = role_override

    # ── Filter 1: drop user/company profiles (Tavily false positives) ────
    before_profile_filter = len(opportunities)
    opportunities = [o for o in opportunities if not _is_user_or_company_profile(o)]
    profile_dropped = before_profile_filter - len(opportunities)
    if profile_dropped:
        _info(f"Dropped {profile_dropped} user/company profile URL(s) — kept job postings only.")

    # ── Filter 2: enrich + verify direct listings via Tavily /extract ────
    # Tavily /extract gives us:
    #   - Page content → real description in `snippet`
    #   - Login-wall / expired detection → drop
    #   - Source normalization (jobgether.com → "jobgether", etc.)
    # Aggregator URLs (e.g. linkedin.com/jobs/foo-jobs-bar) are dropped here too.
    if os.getenv("TAVILY_API_KEY"):
        before_enrich = len(opportunities)
        # Combine skills + certifications so terms like "SAFe", "Scrum Master", "PMP"
        # also count toward skill matching.
        combined_skills = list(profile_data.get("skills") or [])[:25] \
            + list(profile_data.get("certifications") or [])[:10]
        # Allow remote-friendly results unless the user explicitly chose on-site.
        allow_remote = (modality or "").lower() in ("any", "remote", "hybrid", "")
        opportunities = _enrich_listings_via_tavily(
            opportunities,
            candidate_skills=combined_skills,
            candidate_titles=cv_titles,
            location_filter=args.location,
            allow_remote=allow_remote,
        )
        enrich_dropped = before_enrich - len(opportunities)
        if enrich_dropped:
            _info(f"Total {enrich_dropped} listing(s) dropped during Tavily enrichment.")
    else:
        # Legacy fallback when no Tavily key — HEAD/GET availability check only.
        direct_count = sum(1 for o in opportunities if o.get("link_type") == "direct_listing")
        if direct_count:
            _info(f"Checking availability of {direct_count} direct listing URL(s) "
                  "(set TAVILY_API_KEY for richer enrichment) …")
            for opp in opportunities:
                if opp.get("link_type") == "direct_listing" and opp.get("url"):
                    result = _check_url_available(opp["url"])
                    opp["available"] = result["available"]
                    opp["accepting_applications"] = result.get("accepting")
            before_avail_filter = len(opportunities)
            opportunities = [
                o for o in opportunities
                if o.get("link_type") != "direct_listing"
                or (o.get("available") is not False
                    and o.get("accepting_applications") is not False)
            ]
            avail_dropped = before_avail_filter - len(opportunities)
            if avail_dropped:
                _info(f"Dropped {avail_dropped} unavailable / closed listing(s).")

    # Sync the filtered list back into the data dict so the report reflects it.
    data["opportunities"] = opportunities
    data["total_found"] = len(opportunities)

    # ── Retrieve→rerank pipeline ────────────────────────────────────────
    # Body-fetch → embedding rerank → full-body keyword pre-filter → LLM judge.
    # Each stage degrades gracefully when its optional dep is missing.
    if getattr(args, "rerank", True) and opportunities:
        try:
            from src.search_pipeline import run_pipeline
        except Exception as e:
            _warn(f"Could not load src.search_pipeline ({e}); skipping rerank.")
            run_pipeline = None  # type: ignore
        if run_pipeline is not None:
            profile_skills = list((profile_data or {}).get("skills") or [])
            profile_summary = (
                ((profile_data or {}).get("headline") or "") + ". "
                + ((profile_data or {}).get("summary") or "") + " Skills: "
                + ", ".join(profile_skills[:30])
            )
            _info(f"Running search rerank pipeline on {len(opportunities)} candidate(s) "
                  f"(provider={getattr(args, 'embeddings_provider', 'local')}, "
                  f"llm_judge={'on' if getattr(args, 'llm_judge', True) else 'off'}) …")
            try:
                piped = run_pipeline(
                    opportunities,
                    profile_summary=profile_summary.strip(),
                    profile_keywords=profile_skills + (cv_titles or []),
                    target_role=", ".join(role_override or cv_titles or [])[:120],
                    target_seniority=args.seniority or None,
                    target_modality=modality if modality != "any" else None,
                    target_location=args.location,
                    max_to_fetch=min(30, len(opportunities)),
                    top_k_after_rerank=max(args.max_results, 10),
                    min_match=args.min_match or 0,
                    enable_llm_judge=getattr(args, "llm_judge", True),
                    embeddings_provider=getattr(args, "embeddings_provider", "local"),
                )
                stages = piped.get("stages", {})
                _ok(
                    "Rerank pipeline: "
                    + " → ".join(f"{k}={v}" for k, v in stages.items())
                )
                opportunities = piped["opportunities"]
                data["opportunities"] = opportunities
                data["total_found"] = len(opportunities)
                data["rerank_stages"] = stages
                srcs = data.setdefault("sources_used", [])
                if "rerank_pipeline" not in srcs:
                    srcs.append("rerank_pipeline")
            except Exception as e:
                _warn(f"Rerank pipeline raised {e!r}; using pre-rerank list.")

    # Create a timestamped run folder: output/{cv_stem}_{YYYY-MM-DD-HH-MM}/
    run_ts = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
    cv_slug = _slugify(args.cv.stem, max_len=30)
    run_dir = args.output / f"{cv_slug}_{run_ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    out_path = run_dir / "job_search_results.json"
    out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # Generate per-opportunity markdown reports
    report_dir = args.report_dir or (run_dir / "reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_paths: list[Path] = []
    for i, opp in enumerate(opportunities, 1):
        rp = _write_opportunity_report(opp, report_dir, i)
        report_paths.append(rp)
    data["reports_dir"] = str(report_dir.resolve())

    # Reuse the candidate profile we extracted earlier (no double LLM call).

    candidate_name = (
        (profile_data.get("full_name") if profile_data else None)
        or data.get("candidate_name")
        or args.cv.stem
        or "candidate"
    )
    summary_report_path = _write_search_summary_report(
        data, run_dir,
        candidate_name=candidate_name,
        profile_data=profile_data or None,
    )

    elapsed = round(time.time() - started, 1)
    _banner("SEARCH COMPLETE")

    if not opportunities:
        _warn(f"No opportunities returned ({elapsed}s)")
    else:
        _ok(f"Found {len(opportunities)} opportunities ({elapsed}s)")

    print()

    if opportunities:
        if _HAS_RICH:
            table = Table(title="Job opportunities (absolute URLs)",
                          show_header=True, header_style="bold cyan")
            table.add_column("#", style="dim", width=3)
            table.add_column("Source", style="green")
            table.add_column("Title", style="bold", max_width=38)
            table.add_column("Match", justify="right")
            table.add_column("Contract")
            table.add_column("URL")
            for i, opp in enumerate(opportunities[:args.max_results], 1):
                score = opp.get("match_score", 0)
                score_str = f"{score}/100" if score else "-"
                table.add_row(
                    str(i),
                    opp.get("source", "?"),
                    opp.get("title", "")[:38],
                    score_str,
                    opp.get("contract_type") or "-",
                    opp.get("url", ""),
                )
            _console.print(table)
        else:
            for i, opp in enumerate(opportunities, 1):
                print(f"\n[{i}] {opp.get('title', '')}")
                print(f"    Company  : {opp.get('company', '?')}")
                print(f"    Source   : {opp.get('source', '?')}")
                print(f"    URL      : {opp.get('url', '')}")
                if opp.get("apply_url") and opp["apply_url"] != opp.get("url"):
                    print(f"    Apply    : {opp['apply_url']}")
                if opp.get("salary_hint"):
                    print(f"    Salary   : {opp['salary_hint']}")
                if opp.get("contract_type"):
                    print(f"    Contract : {opp['contract_type']}")
                if opp.get("match_score"):
                    print(f"    Match    : {opp['match_score']}/100")
                if opp.get("snippet"):
                    print(f"    {opp['snippet'][:160]}")
                if opp.get("why_relevant"):
                    print(f"    Why      : {opp['why_relevant']}")
                if opp.get("tech_stack"):
                    print(f"    Tech     : {', '.join(opp['tech_stack'][:6])}")
        print()

    _info(f"Run folder   : {run_dir.resolve()}")
    _info(f"Summary MD   : {summary_report_path.resolve()}")
    _info(f"Results JSON : {out_path.resolve()}")
    if report_paths:
        _info(f"Reports dir  : {report_dir.resolve()}  ({len(report_paths)} .md files)")
    return 0 if opportunities else 1


# ─── Subcommand: eval ─────────────────────────────────────────────────────

