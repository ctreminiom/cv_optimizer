"""Wraps the curated JSON files in `src/knowledge_bases/` as CrewAI
JSONKnowledgeSource instances and exposes the matching embedder config.

The embedder defaults to a local `sentence-transformers` model so no API key
is required. Override with CREW_EMBEDDER_PROVIDER=openai|voyage.

Usage:

    agent = Agent(
        config=...,
        knowledge_sources=knowledge_sources_for("backend_engineer"),
        embedder=embedder_config(),
    )
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

_KB_DIR = Path(__file__).resolve().parent / "knowledge_bases"


def embedder_config() -> dict:
    """Return a CrewAI-compatible embedder config.

    Defaults to a local huggingface model so no API key is required.
    """
    provider = os.getenv("CREW_EMBEDDER_PROVIDER", "huggingface").lower()
    if provider == "openai":
        return {
            "provider": "openai",
            "config": {"model": os.getenv("CREW_EMBEDDING_MODEL", "text-embedding-3-small")},
        }
    if provider == "voyage" or provider == "voyageai":
        return {
            "provider": "voyageai",
            "config": {"model": os.getenv("CREW_EMBEDDING_MODEL", "voyage-3-lite")},
        }
    return {
        "provider": "huggingface",
        "config": {"model": os.getenv("CREW_EMBEDDING_MODEL",
                                       "sentence-transformers/all-MiniLM-L6-v2")},
    }


def knowledge_sources_for(role_type: str) -> List:
    """Return JSONKnowledgeSource instances for a given role_type.

    role_type is a canonical token like "backend_engineer", "project_manager",
    "data_scientist". Always includes `_default.json` as a fallback. Returns
    an empty list if CrewAI's knowledge module isn't importable (which gives
    callers a clean degrade-to-tool path).
    """
    try:
        from crewai.knowledge.source.json_knowledge_source import JSONKnowledgeSource
    except ImportError:
        return []

    canonical = (role_type or "_default").lower().replace(" ", "_")
    candidate = _KB_DIR / f"{canonical}.json"
    sources = []
    if candidate.exists():
        sources.append(JSONKnowledgeSource(file_paths=[str(candidate)]))
    default = _KB_DIR / "_default.json"
    if default.exists() and candidate != default:
        sources.append(JSONKnowledgeSource(file_paths=[str(default)]))
    return sources
