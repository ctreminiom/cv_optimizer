"""Classification helpers for URLs and extracted page bodies.

Used by the search command to drop false-positive opportunities (person /
company profiles, LinkedIn aggregator pages, login-walled extracts, stale
postings, foreign-country listings).
"""
from __future__ import annotations

import re

COSTA_RICA_TERMS = [
    "costa rica", "costa-rica", "costarica",
    "san josé", "san jose", "heredia", "cartago", "alajuela",
    "puntarenas", "guanacaste", "limón", "limon", "escazú", "escazu",
    "santa ana", "belén", "belen",
    " cr,", " cr ", " cr.", "(cr)", ",cr",
]

REMOTE_TERMS = [
    "fully remote", "100% remote", "remote-first", "remote first",
    "work from anywhere", "anywhere in latam", "anywhere in latin america",
    "remote position", "remote work", "remote opportunity",
    "trabajo remoto", "trabaja desde casa", "teletrabajo",
    "home office", "work from home", "remote (anywhere",
    "remote, anywhere", "remote within", "open to remote",
    "this is a remote position",
]

# URLs that are person / company profiles rather than postings.
PROFILE_URL_PATTERNS = [
    re.compile(r"linkedin\.com/in/", re.I),
    re.compile(r"linkedin\.com/pub/", re.I),
    re.compile(r"linkedin\.com/company/", re.I),
    re.compile(r"linkedin\.com/school/", re.I),
    re.compile(r"glassdoor\.com/Overview/", re.I),
    re.compile(r"github\.com/[^/]+/?$", re.I),
    re.compile(r"twitter\.com/[^/]+/?$", re.I),
    re.compile(r"x\.com/[^/]+/?$", re.I),
    re.compile(r"facebook\.com/[^/]+/?$", re.I),
    re.compile(r"instagram\.com/[^/]+/?$", re.I),
]

# LinkedIn category/search aggregator URLs (no specific job ID).
LINKEDIN_AGGREGATOR_PATTERNS = [
    re.compile(r"linkedin\.com/jobs/[a-z0-9%-]+-jobs(-[a-z0-9%-]+)*/?(\?|$|#)", re.I),
    re.compile(r"linkedin\.com/jobs/[a-z0-9%-]+-empleos(-[a-z0-9%-]+)*/?(\?|$|#)", re.I),
    re.compile(r"linkedin\.com/jobs/(?!search)[a-z0-9%-]+/?(\?|$|#)", re.I),
]

# URL substring → canonical source name.
DOMAIN_TO_SOURCE = [
    ("jobgether.com",       "jobgether"),
    ("linkedin.com",        "linkedin"),
    ("indeed.com",          "indeed"),
    ("glassdoor.com",       "glassdoor"),
    ("wellfound.com",       "wellfound"),
    ("remoteok.com",        "remoteok"),
    ("remoteok.io",         "remoteok"),
    ("remote.co",           "remote_co"),
    ("computrabajo.",       "computrabajo"),
    ("hireline.io",         "hireline"),
    ("getonbrd.com",        "getonboard"),
    ("weworkremotely.com",  "weworkremotely"),
    ("tecoloco.com",        "tecoloco"),
    ("encuentra24.com",     "encuentra24"),
    ("dice.com",            "dice"),
    ("ziprecruiter.com",    "ziprecruiter"),
    ("workable.com",        "workable"),
    ("greenhouse.io",       "greenhouse"),
    ("lever.co",            "lever"),
    ("ashbyhq.com",         "ashby"),
]

LOGIN_WALL_PHRASES = [
    "sign in to view", "sign in to see", "log in to see", "log in to view",
    "login to apply", "you need to be signed in", "create a free account to",
    "sign up to apply", "join linkedin", "to see who linkedin members",
    "agree & join", "sign in to leverage",
    "linkedin is the world's largest", "make the most of your professional life",
    "join now to see who", "linkedin members worldwide", "agree & join linkedin",
    "by clicking continue to join", "by clicking continue, you agree",
    "welcome back",
    "is the world's largest professional", "ready to start your career",
    "explore careers at", "join our talent network",
]

SLUG_STOP_WORDS = {
    "the", "and", "for", "with", "job", "jobs", "view", "apply",
    "remote", "view-job", "view_job", "in", "at", "of", "to", "from",
    "careers", "career", "position", "opening", "id", "req",
}

STALE_AGE_PATTERNS = [
    re.compile(r"\bposted\s+(\d+)\+?\s+year[s]?\s+ago\b", re.I),
    re.compile(r"\b(\d+)\+?\s+year[s]?\s+ago\b", re.I),
    re.compile(r"\b(?:posted\s+)?([6-9]|1[0-2])\+?\s+months?\s+ago\b", re.I),
    re.compile(r"\bhace\s+(\d+)\+?\s+años?\b", re.I),
    re.compile(r"\bhace\s+([6-9]|1[0-2])\+?\s+meses\b", re.I),
]


def is_user_or_company_profile(opp: dict) -> bool:
    url = opp.get("url") or ""
    return bool(url) and any(p.search(url) for p in PROFILE_URL_PATTERNS)


def is_linkedin_category_aggregator(url: str) -> bool:
    return bool(url) and any(p.search(url) for p in LINKEDIN_AGGREGATOR_PATTERNS)


def normalize_source_from_url(url: str) -> str | None:
    if not url:
        return None
    lower = url.lower()
    for needle, src in DOMAIN_TO_SOURCE:
        if needle in lower:
            return src
    return None


def url_slug_tokens(url: str) -> list[str]:
    """Identifiable tokens from a URL path's slug, used to verify that an
    extracted page body is actually about the job the URL pointed to.
    """
    if not url:
        return []
    path = url.split("?")[0].split("#")[0]
    segments = [s for s in path.split("/") if s]
    if not segments:
        return []
    slug_parts: list[str] = []
    for seg in reversed(segments):
        if seg.isdigit():
            continue
        slug_parts.append(seg)
        if len(slug_parts) >= 2:
            break
    slug = "_".join(reversed(slug_parts))
    slug = re.sub(r"[-_]?\d{4,}$", "", slug)
    raw_tokens = re.split(r"[-_/.]", slug)
    tokens: list[str] = []
    seen: set = set()
    for raw in raw_tokens:
        t = re.sub(r"[^a-zA-Z]", "", raw).lower()
        if len(t) < 3 or t in SLUG_STOP_WORDS or t in seen:
            continue
        seen.add(t)
        tokens.append(t)
    return tokens


def is_stale_listing(content: str, max_months: int = 6) -> bool:
    if not content:
        return False
    lower = content.lower()
    for pat in STALE_AGE_PATTERNS:
        m = pat.search(lower)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except (ValueError, IndexError):
            return True
        if "year" in m.re.pattern or "año" in m.re.pattern:
            return n >= 1
        return n >= max_months
    return False


def content_matches_url_slug(content: str, url: str,
                              min_match_pct: float = 0.4) -> bool:
    """Confirm an extracted body is actually about the URL's job slug. Catches
    ATS 302 redirects to careers indexes.
    """
    tokens = url_slug_tokens(url)
    if len(tokens) < 2:
        return True  # too few tokens to validate
    if not content:
        return False
    lower = content.lower()
    matches = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", lower))
    threshold = max(2, int(round(len(tokens) * min_match_pct)))
    return matches >= threshold


def is_login_walled(content: str) -> bool:
    if not content or len(content.strip()) < 200:
        return True
    lower = content.lower()
    return any(p in lower for p in LOGIN_WALL_PHRASES)


def is_location_relevant(content: str, location: str,
                         allow_remote: bool = True) -> bool:
    """True if the body mentions the target location or, when allow_remote is
    set, indicates the role is remote-friendly.
    """
    if not content:
        return False
    lower = content.lower()

    if location and location.strip().lower() in {"costa rica", "cr", "costa-rica"}:
        if any(t in lower for t in COSTA_RICA_TERMS):
            return True
    loc_lower = (location or "").strip().lower()
    if loc_lower and len(loc_lower) > 2 and loc_lower in lower:
        return True

    if allow_remote:
        if any(t in lower for t in REMOTE_TERMS):
            return True
        if re.search(
            r"\b(?:location|based|position|role|hiring|work|employee)\b"
            r"[^.\n]{0,60}\bremote\b", lower
        ):
            return True
        if re.search(r"\b(?:location|workplace|workplace type|work setup|"
                     r"job type|job mode|modality|tipo de trabajo|"
                     r"modalidad)\s*[:=]\s*remote\b", lower):
            return True
    return False


def summarize_extracted_content(content: str, max_chars: int = 600) -> str:
    """Trim noisy headers/menus and return a clean job-description excerpt."""
    if not content:
        return ""
    content = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", content)
    content = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", content)
    lines: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^[\*\-•]\s+", "", line)
        if not line:
            continue
        low = line.lower()
        if any(skip in low for skip in (
            "cookie", "we use cookies", "skip to", "menu", "subscribe",
            "newsletter", "follow us", "back to", "breadcrumb",
            "table of contents", "sign in", "log in", "create account",
        )):
            continue
        if len(line) < 30 and not line.endswith("."):
            continue
        lines.append(line)
        if sum(len(l) for l in lines) >= max_chars * 1.2:
            break

    text = " ".join(lines).strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_period = cut.rfind(". ")
    if last_period > max_chars * 0.6:
        return cut[:last_period + 1]
    return cut.rstrip() + "…"
