"""
fingerprint.py — Recommendation #15 + §3.3 (split cache).

Computes stable hashes of (CV master) and (job posting) independently so we
can reuse expensive parse outputs even when the *other* input changes. The
final evaluation cache is keyed on the combination plus the run flags.

Layout:
    cache/                          legacy combined cache (still honoured)
    cache/cv/<hash>.json            parsed CandidateProfile per master CV
    cache/jd/<hash>.json            parsed JobPosting per job file
    cache/eval/<hash>.json          full JobReport per (cv,jd,flags)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CACHE_DIR = Path("cache")
CV_CACHE_DIR = CACHE_DIR / "cv"
JD_CACHE_DIR = CACHE_DIR / "jd"
EVAL_CACHE_DIR = CACHE_DIR / "eval"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


# ─── Top-level fingerprint (legacy combined key) ──────────────────────────


def compute_fingerprint(
    cv_path: Path, job_path: Path, skip_cover_letter: bool = False, with_competitor: bool = False
) -> str:
    """Hash the binary content of both files plus run flags. Stable across
    runs — same inputs → same fingerprint."""
    h = hashlib.sha256()
    h.update(cv_path.read_bytes())
    h.update(b"||")
    h.update(job_path.read_bytes())
    h.update(f"||cl={int(skip_cover_letter)}|comp={int(with_competitor)}".encode())
    return h.hexdigest()[:16]


def load_cached(fingerprint: str) -> dict | None:
    """Return the previously saved JobReport dict, or None.
    Checks the new eval/<fp>.json location first, then falls back to the
    legacy cache/<fp>.json layout."""
    new_path = EVAL_CACHE_DIR / f"{fingerprint}.json"
    legacy_path = CACHE_DIR / f"{fingerprint}.json"
    for path in (new_path, legacy_path):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def save_cached(fingerprint: str, report: dict) -> Path:
    EVAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVAL_CACHE_DIR / f"{fingerprint}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def clear_cache() -> int:
    """Wipe ALL cache directories (legacy + split). Returns # files removed."""
    if not CACHE_DIR.exists():
        return 0
    n = 0
    for p in CACHE_DIR.rglob("*.json"):
        try:
            p.unlink()
            n += 1
        except Exception:
            pass
    return n


# ─── Split caches — independent CV / JD / eval (§3.3) ─────────────────────


def cv_fingerprint(cv_path: Path) -> str:
    """Stable fingerprint of the master CV file only."""
    return _hash_file(cv_path)


def jd_fingerprint(job_path: Path) -> str:
    """Stable fingerprint of a job-posting file only."""
    return _hash_file(job_path)


def load_cv_parse(fp: str) -> dict | None:
    path = CV_CACHE_DIR / f"{fp}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cv_parse(fp: str, data: dict) -> Path:
    CV_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CV_CACHE_DIR / f"{fp}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def load_jd_parse(fp: str) -> dict | None:
    path = JD_CACHE_DIR / f"{fp}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_jd_parse(fp: str, data: dict) -> Path:
    JD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = JD_CACHE_DIR / f"{fp}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path
