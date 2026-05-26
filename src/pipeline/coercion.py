"""Defensive coercion helpers for crew/agent outputs.

The crew occasionally returns dict-shaped data as a JSON string, a Python
literal, or — in pathological cases — a set. These helpers normalise that
to dict / list / list-of-dict shapes so downstream code can read fields
without scattering isinstance checks everywhere.
"""
from __future__ import annotations

import json
from typing import Any

__all__ = ["as_dict", "as_list", "as_list_of_dicts", "coerce_task_output"]


def as_dict(value: Any) -> dict:
    """Coerce to a dict. Accepts dict, JSON string, or Python-literal string;
    returns {} for anything else.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            try:
                import ast
                parsed = ast.literal_eval(value)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
    return {}


def as_list(value: Any) -> list:
    """Coerce to a list. Sets/frozensets are sorted by (type, repr) for
    deterministic ordering. Returns [] for None / dict / scalar.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (set, frozenset)):
        try:
            return sorted(value, key=lambda x: (str(type(x).__name__), str(x)))
        except Exception:
            return list(value)
    return []


def as_list_of_dicts(value: Any) -> list[dict]:
    """Coerce to a list of dicts. Drops non-dict items; parses string items
    when they're JSON objects. Returns [] when not list-like.
    """
    if not value:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                value = parsed
            else:
                return []
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            d = as_dict(item)
            if d:
                out.append(d)
    return out


def coerce_task_output(value: Any) -> dict:
    """Coerce a CrewAI TaskOutput (or anything else) to a plain dict.

    Handles the full pydantic → raw → JSON → fallback chain so call sites
    don't each re-implement it:
      1. None → {}
      2. dict → returned as-is
      3. object with .pydantic (Pydantic model) → .model_dump()
      4. object with .raw / plain str → JSON-parsed or {"raw": str}
      5. anything else → {"value": str(value)}
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    pydantic = getattr(value, "pydantic", None)
    if pydantic is not None and hasattr(pydantic, "model_dump"):
        return pydantic.model_dump()
    raw = getattr(value, "raw", value)
    if isinstance(raw, str):
        try:
            result = json.loads(raw)
            if isinstance(result, dict):
                return result
        except Exception:
            pass
        return {"raw": raw}
    return {"value": str(raw)}
