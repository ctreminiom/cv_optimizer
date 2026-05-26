"""Domain knowledge retrieval tool."""

from __future__ import annotations

import json
import re
from pathlib import Path

from crewai.tools import tool

__all__ = ["load_domain_knowledge_base"]

_KB_DIR = Path(__file__).resolve().parent.parent / "knowledge_bases"


@tool("load_domain_knowledge_base")
def load_domain_knowledge_base(role_type: str) -> str:
    """
    Loads the curated knowledge base for a given role_type, returning
    seniority signals, credible-vs-buzzword examples, common interview
    topics, and framing opportunities. Falls back to _default.json if no
    KB exists for the requested role.
    """
    canonical = re.sub(r"\s+", "_", role_type.strip().lower())
    canonical = re.sub(r"[^a-z_]", "", canonical)
    candidates = [
        _KB_DIR / f"{canonical}.json",
        _KB_DIR / f"{canonical.replace('senior_', '')}.json",
        _KB_DIR / "_default.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception:
                continue
    return json.dumps({"error": "no knowledge base available", "role_type": role_type})
