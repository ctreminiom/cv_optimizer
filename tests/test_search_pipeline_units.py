"""Unit tests for decomposed search_pipeline helpers."""
from __future__ import annotations

import json

from src.search_pipeline import _build_judge_prompt, _parse_judge_response


def test_build_judge_prompt_fills_all_slots() -> None:
    op = {"title": "SRE", "company": "Acme", "location": "San José, CR",
          "modality": "remote", "snippet": "Deploy microservices."}
    prompt = _build_judge_prompt(
        op,
        target_role="sre",
        target_seniority="senior",
        target_modality="remote",
        target_location="Costa Rica",
    )
    assert "SRE" in prompt
    assert "Acme" in prompt
    assert "Costa Rica" in prompt
    assert "remote" in prompt


def test_build_judge_prompt_uses_any_for_none_params() -> None:
    op = {"title": "Dev", "company": "X", "location": "", "modality": None, "snippet": ""}
    prompt = _build_judge_prompt(
        op, target_role="", target_seniority=None,
        target_modality=None, target_location="",
    )
    assert "any" in prompt


def test_parse_judge_response_valid_json() -> None:
    payload = json.dumps({"role_match": True, "seniority_match": True,
                          "modality_match": True, "location_match": True})
    result = _parse_judge_response(payload)
    assert result is not None
    assert result["role_match"] is True


def test_parse_judge_response_strips_fences() -> None:
    payload = "```json\n{\"role_match\": false}\n```"
    result = _parse_judge_response(payload)
    assert result == {"role_match": False}


def test_parse_judge_response_returns_none_on_garbage() -> None:
    assert _parse_judge_response("not json at all") is None
    assert _parse_judge_response("") is None
