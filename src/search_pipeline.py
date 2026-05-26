"""Post-processing pipeline for job-search results.

Composed of four independently usable stages:

    fetch_jd_bodies      — pull and clean the full posting
    rerank_by_embeddings — score each posting against the candidate profile
    apply_min_match      — drop postings below a keyword-overlap threshold
    llm_judge            — strict role/seniority/modality/location rubric

`run_pipeline` chains them together with sensible defaults. Every stage
degrades gracefully when its optional dependency is missing, so a zero-key
zero-extras install still returns the deep-link fallback.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

_log = logging.getLogger(__name__)
_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "jd"


# ── JD body fetch ──────────────────────────────────────────────────────────

def _jd_cache_path(url: str) -> Path:
    return _CACHE_DIR / f"{hashlib.sha1(url.encode()).hexdigest()[:24]}.json"


def _fetch_html(url: str, timeout: int = 12) -> str | None:
    try:
        import requests
    except ImportError:
        return None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        return r.text if r.status_code < 400 else None
    except Exception as e:
        _log.debug("fetch_html failed for %s: %s", url, e)
        return None


def _extract_body(html: str) -> str:
    try:
        import trafilatura
        return (trafilatura.extract(html, include_comments=False,
                                     include_tables=False) or "").strip()
    except ImportError:
        # Crude tag-strip fallback so users without trafilatura still benefit
        text = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()


def _read_cached_body(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("body")
    except Exception as e:
        _log.debug("Cache read failed for %s: %s", path, e)
        return None


def _write_cached_body(path: Path, url: str, body: str) -> None:
    try:
        path.write_text(
            json.dumps({"url": url, "fetched_at": int(time.time()), "body": body}),
            encoding="utf-8",
        )
    except Exception as e:
        _log.debug("Cache write failed for %s: %s", path, e)


def _is_aggregator(op: dict[str, Any]) -> bool:
    return op.get("link_type") == "search_url"


def fetch_jd_bodies(opportunities: list[dict[str, Any]], *,
                    max_to_fetch: int = 30,
                    cache: bool = True) -> list[dict[str, Any]]:
    """Fetch and clean the JD body for direct postings. Aggregator pages pass
    through unchanged. Cached on disk by URL hash.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fetched = 0
    out: list[dict[str, Any]] = []
    for raw in opportunities:
        op = dict(raw)
        url = op.get("url", "")
        if _is_aggregator(op) or not url or fetched >= max_to_fetch:
            out.append(op)
            continue

        cache_path = _jd_cache_path(url)
        body = _read_cached_body(cache_path) if cache else None
        if body is None:
            html = _fetch_html(url)
            if html:
                body = _extract_body(html)
                if cache and body:
                    _write_cached_body(cache_path, url, body)
            fetched += 1
        if body:
            op["body"] = body
        out.append(op)
    return out


# ── Embedding reranker ─────────────────────────────────────────────────────

class Embedder(Protocol):
    """Embed a batch of texts into a 2-D array. Return None to signal that
    the backend is unavailable and the caller should fall back."""

    def embed(self, texts: list[str]) -> Any | None: ...


@lru_cache(maxsize=1)
def _load_local_model():
    """Load the sentence-transformer model once and cache it for the process lifetime."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


class _LocalEmbedder:
    """Wraps the cached sentence-transformer model. Instances are stateless."""

    def embed(self, texts: list[str]) -> Any | None:
        try:
            model = _load_local_model()
        except Exception:
            return None
        return model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)


class _OpenAIEmbedder:
    def embed(self, texts: list[str]) -> Any | None:
        if not os.getenv("OPENAI_API_KEY"):
            return None
        try:
            from openai import OpenAI
            import numpy as np
            resp = OpenAI().embeddings.create(model="text-embedding-3-small", input=texts)
            return np.array([d.embedding for d in resp.data])
        except Exception as e:
            _log.debug("OpenAI embedder failed: %s", e)
            return None


class _VoyageEmbedder:
    def embed(self, texts: list[str]) -> Any | None:
        if not os.getenv("VOYAGE_API_KEY"):
            return None
        try:
            import voyageai
            import numpy as np
            resp = voyageai.Client().embed(
                texts=texts, model="voyage-3-lite", input_type="document",
            )
            return np.array(resp.embeddings)
        except Exception as e:
            _log.debug("Voyage embedder failed: %s", e)
            return None


_EMBEDDERS: dict[str, type[Embedder]] = {
    "local": _LocalEmbedder,
    "openai": _OpenAIEmbedder,
    "voyage": _VoyageEmbedder,
}


def _get_embedder(provider: str) -> Embedder:
    cls = _EMBEDDERS.get(provider, _LocalEmbedder)
    return cls()


def _jaccard(query: str, docs: list[str]) -> list[float]:
    """Cheap lexical similarity for when no embedder is available."""
    q = set(re.findall(r"[a-z0-9]+", query.lower()))
    out: list[float] = []
    for d in docs:
        dt = set(re.findall(r"[a-z0-9]+", d.lower()))
        out.append(len(q & dt) / len(q | dt) if q and dt else 0.0)
    return out


def _similarity_scores(profile: str, docs: list[str], provider: str) -> list[float]:
    vecs = _get_embedder(provider).embed([profile, *docs])
    if vecs is None:
        return _jaccard(profile, docs)
    try:
        return (vecs[1:] @ vecs[0]).tolist()  # normalized → dot == cosine
    except Exception as e:
        _log.debug("Embedding similarity computation failed, falling back to Jaccard: %s", e)
        return _jaccard(profile, docs)


def _doc_text(op: dict[str, Any], limit: int = 4000) -> str:
    return (op.get("body") or op.get("snippet") or op.get("title") or "")[:limit]


def rerank_by_embeddings(opportunities: list[dict[str, Any]], *,
                         profile_summary: str,
                         provider: str = "local",
                         top_k: int = 10) -> list[dict[str, Any]]:
    """Sort opportunities by similarity to the candidate profile and return
    the top_k. Aggregator pages are kept at the tail as fallback links.
    """
    if not profile_summary or not opportunities:
        return opportunities[:top_k]

    rankable = [o for o in opportunities if not _is_aggregator(o)]
    aggregators = [o for o in opportunities if _is_aggregator(o)]
    docs = [_doc_text(o) for o in rankable]
    if not docs:
        return opportunities[:top_k]

    for op, score in zip(rankable, _similarity_scores(profile_summary, docs, provider)):
        op["rerank_score"] = int(max(0.0, min(1.0, score)) * 100)

    rankable.sort(key=lambda o: o.get("rerank_score", 0), reverse=True)
    return rankable[:top_k] + aggregators


# ── Keyword-overlap filter ─────────────────────────────────────────────────

def apply_min_match(opportunities: list[dict[str, Any]], *,
                    profile_keywords: list[str],
                    min_match: int) -> list[dict[str, Any]]:
    if min_match <= 0 or not profile_keywords:
        return opportunities
    keywords = {k.lower() for k in profile_keywords if k}
    out: list[dict[str, Any]] = []
    for op in opportunities:
        if _is_aggregator(op):
            out.append(op)
            continue
        text = (op.get("body") or op.get("snippet") or "").lower()
        if not text:
            out.append(op)
            continue
        hits = sum(1 for k in keywords if k in text)
        op["keyword_match_score"] = int(100 * hits / max(1, len(keywords)))
        if op["keyword_match_score"] >= min_match:
            out.append(op)
    return out


# ── LLM judge ──────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """You are a strict job-fit screener.

Score this single opening against the candidate constraints on FOUR axes.
For each axis return 1 (passes) or 0 (fails) and a 1-sentence reason.

Axes:
  role_match: Does the posting's role title align with target_role? (use synonyms when obvious)
  seniority_match: Does the posted seniority match target_seniority?
  modality_match: Does the work modality match target_modality? ("any" passes everything)
  location_match: Is the candidate eligible for this location?

Return STRICT JSON with this exact shape:
{{
  "role_match": {{"pass": 0|1, "reason": "..."}},
  "seniority_match": {{"pass": 0|1, "reason": "..."}},
  "modality_match": {{"pass": 0|1, "reason": "..."}},
  "location_match": {{"pass": 0|1, "reason": "..."}},
  "fails_count": <int 0-4>
}}

Candidate constraints:
  target_role: {target_role}
  target_seniority: {target_seniority}
  target_modality: {target_modality}
  target_location: {target_location}

Posting:
  title: {title}
  company: {company}
  location: {location}
  modality: {modality}
  body_excerpt: {body_excerpt}
"""


def _build_judge_prompt(
    op: dict[str, Any],
    *,
    target_role: str,
    target_seniority: str | None,
    target_modality: str | None,
    target_location: str,
) -> str:
    return _JUDGE_PROMPT.format(
        target_role=target_role or "any",
        target_seniority=target_seniority or "any",
        target_modality=target_modality or "any",
        target_location=target_location or "any",
        title=op.get("title", ""),
        company=op.get("company", ""),
        location=op.get("location", ""),
        modality=op.get("modality") or "unknown",
        body_excerpt=(op.get("body") or op.get("snippet") or "")[:1500],
    )


def _parse_judge_response(text: str) -> dict | None:
    text = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(text)
    except Exception as e:
        _log.debug("Judge response parse failed: %s — raw: %.200s", e, text)
        return None


def _judge_one(
    client: Any,
    model: str,
    op: dict[str, Any],
    *,
    target_role: str,
    target_seniority: str | None,
    target_modality: str | None,
    target_location: str,
) -> dict | None:
    prompt = _build_judge_prompt(
        op,
        target_role=target_role,
        target_seniority=target_seniority,
        target_modality=target_modality,
        target_location=target_location,
    )
    try:
        text = client.complete(
            model=model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_judge_response(text)
    except Exception as e:
        _log.debug("LLM judge call failed for %s: %s", op.get("title"), e)
        return None


def llm_judge(
    opportunities: list[dict[str, Any]],
    *,
    target_role: str,
    target_seniority: str | None,
    target_modality: str | None,
    target_location: str,
    max_fails: int = 1,
    model: str | None = None,
    client: Any = None,
) -> list[dict[str, Any]]:
    """Drop opportunities that fail more than `max_fails` of the four checks."""
    if client is None:
        try:
            from src.llm.client import get_default_client
            client = get_default_client()
        except Exception as e:
            _log.warning("LLM client unavailable — skipping judge stage: %s", e)
            return opportunities

    from src.settings import get_settings
    model_id = model or get_settings().model_haiku

    out: list[dict[str, Any]] = []
    for op in opportunities:
        if _is_aggregator(op):
            out.append(op)
            continue
        verdict = _judge_one(
            client, model_id, op,
            target_role=target_role,
            target_seniority=target_seniority,
            target_modality=target_modality,
            target_location=target_location,
        )
        if verdict is None:
            # On any API failure, keep the opportunity rather than drop it
            out.append(op)
            continue
        op["judge_verdict"] = verdict
        if int(verdict.get("fails_count", 0)) <= max_fails:
            out.append(op)
    return out


# ── Pipeline orchestrator ──────────────────────────────────────────────────

def run_pipeline(opportunities: list[dict[str, Any]], *,
                 profile_summary: str,
                 profile_keywords: list[str],
                 target_role: str = "",
                 target_seniority: str | None = None,
                 target_modality: str | None = None,
                 target_location: str = "",
                 max_to_fetch: int = 30,
                 top_k_after_rerank: int = 10,
                 min_match: int = 0,
                 enable_llm_judge: bool = True,
                 embeddings_provider: str = "local",
                 max_fails: int = 1) -> dict[str, Any]:
    stages: dict[str, int] = {"initial": len(opportunities)}

    with_bodies = fetch_jd_bodies(opportunities, max_to_fetch=max_to_fetch)
    stages["after_body_fetch"] = sum(1 for o in with_bodies if o.get("body"))

    ranked = rerank_by_embeddings(
        with_bodies, profile_summary=profile_summary,
        provider=embeddings_provider, top_k=top_k_after_rerank,
    )
    stages["after_rerank"] = len(ranked)

    filtered = apply_min_match(
        ranked, profile_keywords=profile_keywords, min_match=min_match,
    )
    stages["after_min_match"] = len(filtered)

    final = llm_judge(
        filtered,
        target_role=target_role,
        target_seniority=target_seniority,
        target_modality=target_modality,
        target_location=target_location,
        max_fails=max_fails,
    ) if enable_llm_judge else filtered
    stages["final"] = len(final)

    return {"opportunities": final, "stages": stages}
