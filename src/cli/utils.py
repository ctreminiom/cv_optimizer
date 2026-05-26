"""Pure leaf helpers used by the CLI commands."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SUPPORTED_CV_EXTS = {".docx", ".pdf"}
SENIORITY_ORDER = ["junior", "mid", "senior", "lead"]


def validate_cv_path(cv_path: Path) -> str | None:
    """Return an error message if the CV path is invalid, else None."""
    if not cv_path.exists():
        return f"CV file not found: {cv_path}"
    if cv_path.suffix.lower() not in SUPPORTED_CV_EXTS:
        return (
            f"unsupported CV format: {cv_path.suffix}. "
            f"Supported: {', '.join(sorted(SUPPORTED_CV_EXTS))}"
        )
    return None


def slugify(text: str, max_len: int = 40) -> str:
    """Convert text to a safe filename slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    slug = re.sub(r"[\s_]+", "_", slug)
    return slug[:max_len]


def seniority_levels(requested: str) -> list[str]:
    """Return seniority levels from `requested` down to junior, primary first."""
    try:
        idx = SENIORITY_ORDER.index(requested)
        return list(reversed(SENIORITY_ORDER[: idx + 1]))
    except ValueError:
        return [requested] if requested else []


_ROLE_KEYWORDS: dict[str, list[str]] = {
    "Backend Engineer": [
        "backend",
        "api ",
        "server-side",
        " go ",
        "golang",
        "python",
        "rust",
        "node.js",
        "spring boot",
        "microservices",
    ],
    "Frontend Engineer": [
        "frontend",
        "react",
        "vue",
        "angular",
        "ui/ux",
        "css",
        "typescript front",
        " ux ",
    ],
    "Data Scientist": [
        "data scientist",
        "ml engineer",
        "machine learning",
        "data science",
        "modelo",
        "modelos predictivos",
    ],
    "Project Manager": [
        "project manager",
        "program manager",
        " pm ",
        "project management",
        "administrar proyectos",
        "gestión de proyectos",
    ],
    "DevOps Engineer": [
        "devops",
        "sre",
        "platform engineer",
        "kubernetes",
        "infrastructure",
        "terraform",
        "ci/cd",
    ],
    "Product Manager": ["product manager", "product owner", "product strategy", "roadmap"],
    "QA Engineer": [" qa ", "quality assurance", "automated test", "test engineer"],
    "Marketing Manager": [
        "marketing manager",
        "growth marketing",
        "marketing director",
        "brand manager",
        "cmo ",
    ],
    "Incident Manager": ["incident manager", "major incident", "incident response", "mim "],
}


def _extract_text_from_path(path: Path) -> str:
    text = path.stem.lower()
    try:
        if path.suffix.lower() in (".md", ".txt") and path.exists():
            text += "\n" + path.read_text(encoding="utf-8", errors="ignore")[:4000].lower()
        elif path.suffix.lower() == ".pdf" and path.exists():
            try:
                from pypdf import PdfReader

                pages = PdfReader(str(path)).pages[:2]
                text += "\n" + " ".join((pg.extract_text() or "") for pg in pages)[:4000].lower()
            except Exception:
                pass
    except Exception:
        pass
    return text


def classify_role_type(name_or_path: Any) -> str:
    """Heuristic role classifier. Accepts a Path (reads a file snippet) or any
    string. Falls back to "Practitioner" when no keyword matches.
    """
    text = (
        _extract_text_from_path(name_or_path)
        if isinstance(name_or_path, Path)
        else str(name_or_path).lower()
    )

    scores = {label: sum(1 for t in terms if t in text) for label, terms in _ROLE_KEYWORDS.items()}
    best_label, best_score = max(scores.items(), key=lambda kv: kv[1], default=("Practitioner", 0))
    return best_label if best_score > 0 else "Practitioner"
