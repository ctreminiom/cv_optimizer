"""Loads role_taxonomy.yaml and expands user-supplied role keywords into
recruiter-facing synonyms. Powers query expansion for `search_jobs` and the
role-match check in the LLM judge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "config" / "role_taxonomy.yaml"

_cache: Dict[str, List[str]] | None = None


def _load() -> Dict[str, List[str]]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        import yaml
    except ImportError:
        _cache = {}
        return _cache
    if not _TAXONOMY_PATH.exists():
        _cache = {}
        return _cache
    raw = yaml.safe_load(_TAXONOMY_PATH.read_text(encoding="utf-8")) or {}
    # Normalise to lowercase
    out: Dict[str, List[str]] = {}
    for canonical, alts in raw.items():
        canon_key = canonical.replace("_", " ").lower()
        out[canon_key] = [str(a).lower() for a in (alts or [])]
        # Also map canonical_with_underscores → same synonyms
        out[str(canonical).lower()] = out[canon_key]
    _cache = out
    return _cache


def expand_keywords(keywords: List[str]) -> Dict[str, List[str]]:
    """Return a {input_keyword: [synonyms]} map for any keyword that has
    a taxonomy entry. Caller decides how aggressively to expand.
    """
    taxonomy = _load()
    out: Dict[str, List[str]] = {}
    for kw in keywords:
        k = kw.lower().strip()
        if k in taxonomy:
            out[kw] = list(taxonomy[k])
            continue
        # Partial match (e.g., "PM" inside "product_manager" synonyms list)
        for canonical, alts in taxonomy.items():
            if k in alts or k == canonical:
                out[kw] = list({*alts, canonical}) if canonical not in out.get(kw, []) else out[kw]
                break
    return out


def all_aliases() -> Dict[str, str]:
    """Reverse map alias → canonical for matching against returned postings."""
    taxonomy = _load()
    out: Dict[str, str] = {}
    for canonical, alts in taxonomy.items():
        out[canonical] = canonical
        for a in alts:
            out[a] = canonical
    return out
