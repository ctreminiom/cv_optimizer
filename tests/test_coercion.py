"""Tests for src/pipeline/coercion.py."""
from __future__ import annotations

from src.pipeline.coercion import as_dict, as_list, as_list_of_dicts, coerce_task_output


def test_as_dict_passes_dict_through():
    assert as_dict({"a": 1}) == {"a": 1}


def test_as_dict_parses_json_string():
    assert as_dict('{"a": 1, "b": 2}') == {"a": 1, "b": 2}


def test_as_dict_returns_empty_for_invalid():
    assert as_dict(None) == {}
    assert as_dict("not json") == {}
    assert as_dict(42) == {}
    assert as_dict('[1, 2, 3]') == {}  # list, not dict


def test_as_dict_parses_python_literal():
    assert as_dict("{'a': 1}") == {"a": 1}


def test_as_list_passes_list_through():
    assert as_list([1, 2, 3]) == [1, 2, 3]


def test_as_list_handles_tuple_and_set():
    assert as_list((1, 2)) == [1, 2]
    out = as_list({3, 1, 2})
    assert sorted(out) == [1, 2, 3]


def test_as_list_returns_empty_for_dict_or_scalar():
    assert as_list({"a": 1}) == []
    assert as_list("anything") == []
    assert as_list(42) == []
    assert as_list(None) == []


def test_as_list_of_dicts_passes_through():
    assert as_list_of_dicts([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]


def test_as_list_of_dicts_parses_json_string():
    assert as_list_of_dicts('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


def test_as_list_of_dicts_drops_non_dict_items():
    assert as_list_of_dicts([{"a": 1}, "string", 42, None, {"b": 2}]) == [{"a": 1}, {"b": 2}]


def test_as_list_of_dicts_parses_dict_strings():
    assert as_list_of_dicts(['{"a": 1}', '{"b": 2}']) == [{"a": 1}, {"b": 2}]


# ── coerce_task_output ──────────────────────────────────────────────────────

def test_coerce_task_output_none_returns_empty():
    assert coerce_task_output(None) == {}


def test_coerce_task_output_dict_passthrough():
    assert coerce_task_output({"a": 1}) == {"a": 1}


def test_coerce_task_output_pydantic_model():
    class _FakePydantic:
        def model_dump(self):
            return {"skill": "Go"}

    class _FakeTaskOut:
        pydantic = _FakePydantic()

    assert coerce_task_output(_FakeTaskOut()) == {"skill": "Go"}


def test_coerce_task_output_raw_json_string():
    class _FakeTaskOut:
        pydantic = None
        raw = '{"skills": ["Python"]}'

    result = coerce_task_output(_FakeTaskOut())
    assert result == {"skills": ["Python"]}


def test_coerce_task_output_raw_non_json_wrapped_in_raw_key():
    class _FakeTaskOut:
        pydantic = None
        raw = "just some text"

    result = coerce_task_output(_FakeTaskOut())
    assert result == {"raw": "just some text"}


def test_coerce_task_output_plain_string_wrapped():
    result = coerce_task_output("hello")
    assert result == {"raw": "hello"}
