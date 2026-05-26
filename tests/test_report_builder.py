"""Tests for src/report/builder.py and src/report/_extractors.py (Phase 3b)."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.report.builder import (
    TaskExtractor,
    _REGISTRY,
    _coerce_value,
    augment_report,
    register_extractor,
)
from src.constants import TASK_PARSE_JOB, TASK_HR_EVAL, TASK_PARSE_CV


# ── Helpers ───────────────────────────────────────────────────────────────────

class _TaskOut:
    def __init__(self, name="", pydantic=None, raw=None, task=None):
        self.name = name
        self.pydantic = pydantic
        self.raw = raw
        self.task = task


class _Pyd:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return self._data


def _make_pyd(cls_name, data):
    return type(cls_name, (_Pyd,), {})(data)


class _CrewResult:
    def __init__(self, tasks_output):
        self.tasks_output = tasks_output


# ── _coerce_value ─────────────────────────────────────────────────────────────

def test_coerce_value_pydantic_wins() -> None:
    pyd = _make_pyd("JobPosting", {"title": "Eng"})
    out = _TaskOut(pydantic=pyd)
    assert _coerce_value(out) == {"title": "Eng"}


def test_coerce_value_raw_json() -> None:
    out = _TaskOut(raw='{"skills": ["Go"]}')
    assert _coerce_value(out) == {"skills": ["Go"]}


def test_coerce_value_raw_with_fenced_code_block() -> None:
    out = _TaskOut(raw='```json\n{"x": 1}\n```')
    assert _coerce_value(out) == {"x": 1}


def test_coerce_value_raw_invalid_json_returns_dict_with_raw() -> None:
    out = _TaskOut(raw="not json at all")
    result = _coerce_value(out)
    assert isinstance(result, dict)
    assert "raw" in result


def test_coerce_value_no_data_returns_none() -> None:
    out = _TaskOut()
    assert _coerce_value(out) is None


# ── register_extractor ────────────────────────────────────────────────────────

def test_register_extractor_with_instance() -> None:
    before = len(_REGISTRY)

    class _MyExtractor:
        def extract(self, task_out: Any) -> tuple[str, Any] | None:
            return None

    instance = _MyExtractor()
    register_extractor(instance)
    assert len(_REGISTRY) == before + 1
    assert _REGISTRY[-1] is instance
    _REGISTRY.pop()  # cleanup


def test_register_extractor_with_class_instantiates() -> None:
    before = len(_REGISTRY)

    @register_extractor
    class _ClassExtractor:
        def extract(self, task_out: Any) -> tuple[str, Any] | None:
            return None

    assert len(_REGISTRY) == before + 1
    assert isinstance(_REGISTRY[-1], _ClassExtractor)
    _REGISTRY.pop()


# ── augment_report ────────────────────────────────────────────────────────────

def test_augment_report_empty_result_returns_report() -> None:
    result = MagicMock()
    result.tasks_output = []
    report = {"existing": "data"}
    out = augment_report(report, result)
    assert out["existing"] == "data"


def test_augment_report_bad_crew_result_returns_report() -> None:
    class _Bad:
        @property
        def tasks_output(self):
            raise RuntimeError("boom")

    report = {"x": 1}
    out = augment_report(report, _Bad())
    assert out == {"x": 1}


def test_augment_report_list_append() -> None:
    from src.constants import TASK_HR_EVAL
    ev = _make_pyd("AgentEvaluation", {"agent_role": "HR", "score": 80})
    out = _TaskOut(name=TASK_HR_EVAL, pydantic=ev)
    report = augment_report({}, _CrewResult([out]))
    assert "evaluations" in report
    assert isinstance(report["evaluations"], list)
    assert report["evaluations"][0]["agent_role"] == "HR"


def test_augment_report_does_not_overwrite_existing_key() -> None:
    pyd = _make_pyd("JobPosting", {"title": "New"})
    out = _TaskOut(name=TASK_PARSE_JOB, pydantic=pyd)
    report = augment_report({"job": {"title": "Old"}}, _CrewResult([out]))
    assert report["job"]["title"] == "Old"


def test_augment_report_pydantic_class_fallback() -> None:
    pyd = _make_pyd("JobPosting", {"title": "Fallback"})
    out = _TaskOut(name="", pydantic=pyd)
    report = augment_report({}, _CrewResult([out]))
    assert report.get("job", {}).get("title") == "Fallback"


def test_augment_report_substr_fallback() -> None:
    task = type("T", (), {"name": "", "description": "parse_cv from document"})()
    out = _TaskOut(name="", raw='{"skills": ["Python"]}', task=task)
    report = augment_report({}, _CrewResult([out]))
    assert report.get("candidate_profile", {}).get("skills") == ["Python"]


# ── TaskExtractor protocol ────────────────────────────────────────────────────

def test_named_extractor_satisfies_protocol() -> None:
    from src.report._extractors import _NamedTaskExtractor
    instance = _NamedTaskExtractor()
    assert isinstance(instance, TaskExtractor)
