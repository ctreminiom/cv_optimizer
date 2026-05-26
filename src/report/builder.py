"""Assemble a JobReport dict from CrewAI task outputs.

Uses a registry of TaskExtractor instances so new tasks can register
themselves without modifying augment_report().
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, runtime_checkable

__all__ = ["augment_report", "register_extractor", "TaskExtractor"]


@runtime_checkable
class TaskExtractor(Protocol):
    """Extract (report_key, value) from one CrewAI TaskOutput."""

    def extract(self, task_out: Any) -> tuple[str, Any] | None: ...


_REGISTRY: list[TaskExtractor] = []


def register_extractor(extractor: TaskExtractor) -> TaskExtractor:
    """Register an extractor; returns it so it can be used as a class decorator.

    When used as ``@register_extractor`` on a class, the class is instantiated
    automatically so callers don't have to manage that themselves.
    """
    import inspect

    _REGISTRY.append(extractor() if inspect.isclass(extractor) else extractor)
    return extractor


def _coerce_value(task_out: Any) -> Any | None:
    """Pull structured data out of a task output — pydantic first, raw JSON fallback."""
    pydantic_obj = getattr(task_out, "pydantic", None)
    if pydantic_obj is not None:
        return pydantic_obj.model_dump()
    raw = getattr(task_out, "raw", None)
    if not raw:
        return None
    raw = raw if isinstance(raw, str) else str(raw)
    stripped = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    brace = stripped.find("{")
    if brace > 0:
        stripped = stripped[brace:]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return {"raw": raw[:2000]}


def augment_report(report: dict, crew_result: Any) -> dict:
    """Apply all registered extractors to each task output in crew_result."""
    try:
        tasks_output = getattr(crew_result, "tasks_output", None) or []
    except Exception:
        return report

    for task_out in tasks_output:
        for extractor in _REGISTRY:
            try:
                result = extractor.extract(task_out)
                if result is None:
                    continue
                key, value = result
                if value is None:
                    continue
                if isinstance(key, tuple) and key[1] == "list_append":
                    report.setdefault(key[0], [])
                    if isinstance(report[key[0]], list):
                        report[key[0]].append(value)
                elif not report.get(key):
                    report[key] = value
                break  # first matching extractor wins
            except Exception:
                continue
    return report
