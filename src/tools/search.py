"""Job search tools — query public job boards and score results."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from crewai.tools import tool

__all__ = ["search_jobs"]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_DEFAULT_NEGATIVE_KEYWORDS: frozenset[str] = frozenset(
    {
        "internship",
        "unpaid",
        "volunteer",
        "commission only",
    }
)


def _normalize_for_dedupe(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


def _dedupe_key(item: dict[str, Any]) -> str:
    """Hash of normalized (title + company + city) — collapses the same posting
    listed on multiple boards under a single key."""
    title = _normalize_for_dedupe(item.get("title", ""))
    company = _normalize_for_dedupe(item.get("company", ""))
    city = _normalize_for_dedupe((item.get("location") or "").split(",")[0])
    return hashlib.sha1(f"{title}|{company}|{city}".encode()).hexdigest()[:16]


def _is_aggregator(item: dict[str, Any]) -> bool:
    return item.get("link_type") == "search_url"


def _matches_negative(item: dict[str, Any], exclude: list[str]) -> bool:
    haystack = " ".join(
        [
            item.get("title", ""),
            item.get("snippet", ""),
            item.get("company", ""),
        ]
    ).lower()
    return any(term.lower() in haystack for term in exclude if term)


def _location_matches(item: dict[str, Any], location: str) -> bool:
    if _is_aggregator(item):
        return True
    item_loc = (item.get("location") or "").lower()
    if not item_loc:
        return True
    needle = location.lower().strip()
    return needle in item_loc or any(part.strip() in item_loc for part in needle.split(","))


def _expand_with_synonyms(
    role_keywords: list[str], synonyms_map: dict[str, list[str]]
) -> list[str]:
    expanded: list[str] = list(role_keywords)
    seen = {t.lower() for t in expanded}
    for canonical, alts in synonyms_map.items():
        if canonical.lower() not in (k.lower() for k in role_keywords):
            continue
        for alt in alts:
            if alt and alt.lower() not in seen:
                expanded.append(alt)
                seen.add(alt.lower())
    return expanded


def _resolve_seniority_levels(seniority_levels: Any, seniority: str | None) -> list[str | None]:
    if seniority_levels:
        if isinstance(seniority_levels, list):
            return [s for s in seniority_levels if s]
        return [s.strip() for s in str(seniority_levels).split(",") if s.strip()]
    return [seniority] if seniority else [None]


def _build_search_query(
    role_terms: list[str], *, level: str | None, extra_keywords: list[str], modality: str | None
) -> str:
    query = " ".join(role_terms[:5])
    if level:
        query = f"{level} {query}".strip()
    if extra_keywords:
        query = f"{query} {' '.join(extra_keywords[:3])}".strip()
    if modality == "remote":
        query = f"remote {query}".strip()
    return query


def _filter_and_dedupe(
    results: list[dict[str, Any]],
    *,
    exclude_keywords: list[str],
    exact_location: bool,
    location: str,
    contract_type: str | None,
    max_results: int,
) -> list[dict[str, Any]]:
    seen_url: set = set()
    seen_dedupe: set = set()
    out: list[dict[str, Any]] = []
    for item in results:
        if _matches_negative(item, exclude_keywords):
            continue
        if exact_location and not _location_matches(item, location):
            continue
        url = item.get("url", "")
        if not url or url in seen_url:
            continue
        key = _dedupe_key(item)
        # Aggregator pages collide on (title + company="(multiple)") — keep
        # each board's search page even though the dedupe key matches.
        if not _is_aggregator(item) and key in seen_dedupe:
            continue
        seen_url.add(url)
        seen_dedupe.add(key)
        item["dedupe_key"] = key
        if contract_type and not item.get("contract_type"):
            item["contract_type"] = contract_type
        out.append(item)
        if len(out) >= max_results:
            break
    return out


@tool("search_jobs")
def search_jobs(input_json: str) -> str:
    """
    Search public job boards for openings matching the candidate profile.
    Input JSON: {
        "role_keywords": ["go", "backend", ...],
        "location": "Costa Rica",
        "seniority": "senior" | null,
        "seniority_levels": ["mid", "senior"] | "mid,senior" | null,
        "modality": "remote" | null,
        "max_results": 20,
        "keywords": ["extra", "terms"],
        "contract_type": "full_time" | "contract" | null,
        "include_sources": ["linkedin", "glassdoor", ...] | null,

        // optional quality filters
        "max_age_days": 30,
        "exclude_keywords": ["internship", "unpaid"],
        "exact_location": false,
        "synonyms": {"product manager": ["pm", "sr pm"]}
    }
    Returns: list of JobOpportunity dicts WITH ABSOLUTE URLs.

    Uses Tavily (TAVILY_API_KEY) or Serper (SERPER_API_KEY) if configured;
    otherwise builds direct deep-link search URLs to LinkedIn / Indeed CR /
    Glassdoor / Wellfound / RemoteOK / Computrabajo / Hireline / Get on Board /
    WeWorkRemotely / Tecoloco / Encuentra24 / Dice so the user can click through.
    """
    try:
        params = json.loads(input_json)
    except Exception as e:
        return json.dumps({"error": f"invalid input: {e}"})

    role_keywords = params.get("role_keywords", [])
    location = params.get("location", "Costa Rica")
    seniority = params.get("seniority")
    modality = params.get("modality")
    max_results = int(params.get("max_results", 20))
    extra_keywords = params.get("keywords", [])
    contract_type = params.get("contract_type")
    include_sources = params.get("include_sources")

    max_age_days = params.get("max_age_days")
    exclude_keywords = list(_DEFAULT_NEGATIVE_KEYWORDS) + list(params.get("exclude_keywords") or [])
    exact_location = bool(params.get("exact_location", False))
    synonyms_map: dict[str, list[str]] = params.get("synonyms") or {}

    expanded_terms = _expand_with_synonyms(role_keywords, synonyms_map)
    levels_to_search = _resolve_seniority_levels(params.get("seniority_levels"), seniority)

    results: list[dict[str, Any]] = []
    sources_used: list[str] = []
    queries_used: list[str] = []

    for level in levels_to_search:
        query = _build_search_query(
            expanded_terms,
            level=level,
            extra_keywords=extra_keywords,
            modality=modality,
        )
        provider_location = f'"{location}"' if exact_location else location

        # Tavily covers the deep web; Serper covers Google Jobs vertical.
        if os.getenv("TAVILY_API_KEY"):
            r, q = _search_tavily(query, provider_location, max_results, max_age_days=max_age_days)
            for item in r:
                item.setdefault("seniority", level)
            results.extend(r)
            if "tavily" not in sources_used:
                sources_used.append("tavily")
            queries_used.extend(q)
        if os.getenv("SERPER_API_KEY"):
            r, q = _search_serper(query, location, max_results, max_age_days=max_age_days)
            for item in r:
                item.setdefault("seniority", level)
            results.extend(r)
            if "serper" not in sources_used:
                sources_used.append("serper")
            queries_used.extend(q)

        deeplinks, dl_queries = _build_deep_links(
            query,
            location,
            modality=modality,
            include_sources=include_sources,
            seniority=level,
        )
        results.extend(deeplinks)
        queries_used.extend(dl_queries)

    if "deep_links" not in sources_used:
        sources_used.append("deep_links")

    unique = _filter_and_dedupe(
        results,
        exclude_keywords=exclude_keywords,
        exact_location=exact_location,
        location=location,
        contract_type=contract_type,
        max_results=max_results,
    )

    return json.dumps(
        {
            "total_found": len(unique),
            "opportunities": unique,
            "sources_used": sources_used,
            "search_queries_used": queries_used,
            "filters_applied": {
                "exclude_keywords": exclude_keywords,
                "exact_location": exact_location,
                "max_age_days": max_age_days,
                "synonyms_expanded": len(expanded_terms) - len(role_keywords),
            },
        }
    )


_ALL_SOURCES = [
    "linkedin",
    "indeed_cr",
    "glassdoor",
    "wellfound",
    "remoteok",
    "computrabajo",
    "hireline",
    "getonboard",
    "weworkremotely",
    "tecoloco",
    "encuentra24",
    "dice",
    "ziprecruiter",
]


def _build_deep_links(
    query: str,
    location: str,
    modality: str | None = None,
    include_sources: list[str] | None = None,
    seniority: str | None = None,
) -> tuple:
    """Generate absolute deep-link URLs to 13+ job boards.

    include_sources: if set, only emit boards whose source key is in the list.
    seniority: stamped on each link dict so callers can group by level.
    """
    q_url = urllib.parse.quote_plus(query)
    loc_url = urllib.parse.quote_plus(location)
    is_remote = modality == "remote"

    def _want(src: str) -> bool:
        if include_sources is None:
            return True
        return src in include_sources

    def _link(**kw) -> dict[str, Any]:
        kw.setdefault("seniority", seniority)
        return kw

    queries: list[str] = []
    links: list[dict[str, Any]] = []

    if _want("linkedin"):
        queries.append(f"site:linkedin.com {query} {location}")
        remote_flag = "&f_WT=2" if is_remote else ""
        links.append(
            _link(
                title=f"LinkedIn — {query} in {location}",
                company="(multiple)",
                location=location,
                modality="remote" if is_remote else None,
                snippet="Browse all matching openings on LinkedIn Jobs.",
                url=f"https://www.linkedin.com/jobs/search/?keywords={q_url}&location={loc_url}{remote_flag}",
                source="linkedin",
                link_type="search_url",
            )
        )

    if _want("indeed_cr"):
        queries.append(f"site:cr.indeed.com {query}")
        remote_flag = "&remotejob=1" if is_remote else ""
        links.append(
            _link(
                title=f"Indeed CR — {query}",
                company="(multiple)",
                location=location,
                modality="remote" if is_remote else None,
                snippet="Browse all matching openings on Indeed Costa Rica.",
                url=f"https://cr.indeed.com/jobs?q={q_url}&l={loc_url}{remote_flag}",
                source="indeed_cr",
                link_type="search_url",
            )
        )

    if _want("glassdoor"):
        queries.append(f"site:glassdoor.com {query} {location}")
        links.append(
            _link(
                title=f"Glassdoor — {query} in {location}",
                company="(multiple)",
                location=location,
                modality=None,
                snippet="Browse openings with company reviews and salary data on Glassdoor.",
                url=f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q_url}&locT=N&locId=0",
                source="glassdoor",
                link_type="search_url",
            )
        )

    if _want("wellfound"):
        queries.append(f"site:wellfound.com {query}")
        links.append(
            _link(
                title=f"Wellfound (AngelList) — {query}",
                company="(multiple)",
                location=location,
                modality="remote" if is_remote else None,
                snippet="Startup & tech jobs on Wellfound (formerly AngelList Talent).",
                url=f"https://wellfound.com/jobs?q={q_url}&l={loc_url}",
                source="wellfound",
                link_type="search_url",
            )
        )

    if _want("remoteok"):
        queries.append(f"site:remoteok.com {query}")
        links.append(
            _link(
                title=f"RemoteOK — {query} (remote)",
                company="(multiple)",
                location="Remote",
                modality="remote",
                snippet="Curated remote-only tech and knowledge-worker jobs on RemoteOK.",
                url=f"https://remoteok.com/remote-{q_url.replace('+', '-')}-jobs",
                source="remoteok",
                link_type="search_url",
            )
        )

    if _want("computrabajo"):
        queries.append(f"site:computrabajo.cr {query}")
        links.append(
            _link(
                title=f"Computrabajo CR — {query}",
                company="(multiple)",
                location=location,
                modality=None,
                snippet="Costa Rica's largest Spanish-language job board.",
                url=f"https://www.computrabajo.cr/trabajo-de-{q_url.replace('+', '-')}",
                source="computrabajo",
                link_type="search_url",
            )
        )

    if _want("hireline"):
        queries.append(f"site:hireline.io {query}")
        links.append(
            _link(
                title=f"Hireline — {query}",
                company="(multiple)",
                location=location,
                modality="remote" if is_remote else None,
                snippet="Latin America-focused remote tech jobs on Hireline.",
                url=f"https://hireline.io/jobs?search={q_url}",
                source="hireline",
                link_type="search_url",
            )
        )

    if _want("getonboard"):
        queries.append(f"site:getonbrd.com {query}")
        links.append(
            _link(
                title=f"Get on Board — {query}",
                company="(multiple)",
                location=location,
                modality="remote" if is_remote else None,
                snippet="Latin American remote-friendly tech jobs on Get on Board.",
                url=f"https://www.getonbrd.com/jobs?query={q_url}",
                source="getonboard",
                link_type="search_url",
            )
        )

    if _want("weworkremotely"):
        queries.append(f"site:weworkremotely.com {query}")
        links.append(
            _link(
                title=f"WeWorkRemotely — {query} (remote)",
                company="(multiple)",
                location="Remote",
                modality="remote",
                snippet="One of the largest remote-only job boards. Tech, design, and more.",
                url=f"https://weworkremotely.com/remote-jobs/search?term={q_url}",
                source="weworkremotely",
                link_type="search_url",
            )
        )

    if _want("tecoloco"):
        queries.append(f"site:tecoloco.com {query} Costa Rica")
        links.append(
            _link(
                title=f"Tecoloco CR — {query}",
                company="(multiple)",
                location=location,
                modality=None,
                snippet="Central-American job board with strong Costa Rica presence.",
                url=f"https://www.tecoloco.com/bolsa-de-trabajo/costa-rica/?buscar={q_url}",
                source="tecoloco",
                link_type="search_url",
            )
        )

    if _want("encuentra24"):
        queries.append(f"site:encuentra24.com {query}")
        links.append(
            _link(
                title=f"Encuentra24 — {query}",
                company="(multiple)",
                location=location,
                modality=None,
                snippet="Central American classifieds and job board.",
                url=f"https://www.encuentra24.com/costa-rica-es/empleos?q={q_url}",
                source="encuentra24",
                link_type="search_url",
            )
        )

    if _want("dice"):
        queries.append(f"site:dice.com {query}")
        links.append(
            _link(
                title=f"Dice — {query} (tech)",
                company="(multiple)",
                location=location,
                modality="remote" if is_remote else None,
                snippet="Tech-specialist job board popular in the US/LATAM remote market.",
                url=f"https://www.dice.com/jobs?q={q_url}&l={loc_url}{'&remote=true' if is_remote else ''}",
                source="dice",
                link_type="search_url",
            )
        )

    if _want("ziprecruiter"):
        queries.append(f"site:ziprecruiter.com {query}")
        links.append(
            _link(
                title=f"ZipRecruiter — {query}",
                company="(multiple)",
                location=location,
                modality=None,
                snippet="Broad-market job board aggregating millions of US/remote postings.",
                url=f"https://www.ziprecruiter.com/candidate/search?search={q_url}&location={loc_url}",
                source="ziprecruiter",
                link_type="search_url",
            )
        )

    return links, queries


def _retry_http_post(
    url: str,
    *,
    json_body: dict,
    headers: dict | None = None,
    timeout: int = 30,
    max_attempts: int = 3,
) -> Any:
    """POST with exponential-backoff retry on 429/5xx/timeout.

    Uses tenacity when available; degrades to a simple manual retry loop
    so the tool still works in minimal environments.
    """
    import requests as _rq

    try:
        from tenacity import (
            retry,
            retry_if_exception_type,
            stop_after_attempt,
            wait_exponential_jitter,
        )
    except ImportError:
        # Fallback: simple loop, same exit semantics
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                r = _rq.post(url, json=json_body, headers=headers or {}, timeout=timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    raise _rq.HTTPError(f"retryable status {r.status_code}")
                r.raise_for_status()
                return r
            except (_rq.HTTPError, _rq.Timeout, _rq.ConnectionError) as e:
                last_exc = e
                if attempt < max_attempts - 1:
                    time.sleep(2**attempt + 0.5)
        if last_exc:
            raise last_exc from last_exc
        return None

    @retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception_type((_rq.HTTPError, _rq.Timeout, _rq.ConnectionError)),
        reraise=True,
    )
    def _do() -> Any:
        r = _rq.post(url, json=json_body, headers=headers or {}, timeout=timeout)
        if r.status_code == 429 or r.status_code >= 500:
            raise _rq.HTTPError(f"retryable status {r.status_code}")
        r.raise_for_status()
        return r

    return _do()


def _search_tavily(
    query: str, location: str, max_results: int, max_age_days: int | None = None
) -> tuple:
    """Real search via Tavily (https://tavily.com)."""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return [], []

    # NOTE: jobgether.com/offer/<id>-<slug> is each posting's canonical URL.
    # The /offer/ path is critical — without it Tavily mostly returns category
    # pages (jobgether.com/remote-jobs/...) which are aggregators.
    full_query = (
        f"{query} jobs {location} "
        "site:jobgether.com/offer OR site:linkedin.com/jobs/view OR "
        "site:cr.indeed.com OR site:glassdoor.com OR site:wellfound.com OR "
        "site:computrabajo.cr OR site:hireline.io OR site:getonbrd.com OR "
        "site:tecoloco.com OR site:weworkremotely.com OR site:remoteok.com OR "
        "site:greenhouse.io OR site:lever.co OR site:ashbyhq.com"
    )
    payload: dict = {
        "api_key": api_key,
        "query": full_query,
        "max_results": max_results,
        "search_depth": "advanced",
    }
    if max_age_days and max_age_days > 0:
        payload["days"] = max_age_days
    try:
        resp = _retry_http_post("https://api.tavily.com/search", json_body=payload, timeout=30)
        data = resp.json()
    except Exception:
        return [], [full_query]

    _DOMAIN_SOURCE = {
        "jobgether.com": "jobgether",
        "linkedin.com": "linkedin",
        "indeed.com": "indeed_cr",
        "glassdoor.com": "glassdoor",
        "wellfound.com": "wellfound",
        "computrabajo.cr": "computrabajo",
        "hireline.io": "hireline",
        "getonbrd.com": "getonboard",
        "weworkremotely.com": "weworkremotely",
        "tecoloco.com": "tecoloco",
        "encuentra24.com": "encuentra24",
        "dice.com": "dice",
        "ziprecruiter.com": "ziprecruiter",
        "remoteok.com": "remoteok",
        "greenhouse.io": "greenhouse",
        "lever.co": "lever",
        "ashbyhq.com": "ashby",
    }
    out: list[dict[str, Any]] = []
    for item in data.get("results", []):
        url = item.get("url", "")
        source = "unknown"
        for domain, src in _DOMAIN_SOURCE.items():
            if domain in url:
                source = src
                break
        out.append(
            {
                "title": item.get("title", ""),
                "company": "(see posting)",
                "location": location,
                "modality": None,
                "snippet": (item.get("content") or "")[:300],
                "url": url,
                "source": source,
                "link_type": "direct_listing",
            }
        )
    return out, [full_query]


def _search_serper(
    query: str, location: str, max_results: int, max_age_days: int | None = None
) -> tuple:
    """Real search via Serper (https://serper.dev)."""
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return [], []

    full_query = f"{query} jobs {location}"
    payload: dict = {"q": full_query, "location": location, "num": max_results}
    if max_age_days:
        # qdr=d (day), w (week), m (month), y (year) — pick the smallest bucket fitting max_age_days
        if max_age_days <= 1:
            payload["tbs"] = "qdr:d"
        elif max_age_days <= 7:
            payload["tbs"] = "qdr:w"
        elif max_age_days <= 31:
            payload["tbs"] = "qdr:m"
        else:
            payload["tbs"] = "qdr:y"
    try:
        resp = _retry_http_post(
            "https://google.serper.dev/jobs",
            json_body=payload,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=30,
        )
        data = resp.json()
    except Exception:
        return [], [full_query]

    out: list[dict[str, Any]] = []
    for item in data.get("jobs", []):
        out.append(
            {
                "title": item.get("title", ""),
                "company": item.get("company", "(see posting)"),
                "location": item.get("location", location),
                "modality": None,
                "posted_date": item.get("detected_extensions", {}).get("posted_at")
                or item.get("postedAt"),
                "snippet": (item.get("description") or "")[:300],
                "url": item.get("link") or item.get("share_link") or "",
                "source": "serper_jobs",
                "link_type": "direct_listing",
            }
        )
    return out, [full_query]
