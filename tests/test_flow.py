"""Smoke tests for CvOptimizerFlow (A4 + B4).

We deliberately don't kickoff() — that would call the live Anthropic API.
We just verify the module imports, the state model is consistent, and the
file-hash helper is deterministic.
"""

from __future__ import annotations

import hashlib

from src.flow import CvState, _hash_file, is_available


def test_state_defaults_are_safe():
    s = CvState()
    assert s.cv_path == ""
    assert s.job_path == ""
    assert s.phase == "init"
    assert s.with_competitor is False
    assert s.evaluations == {}
    assert s.errors == []


def test_state_round_trips_through_json():
    s = CvState(cv_path="/tmp/cv.pdf", job_path="/tmp/job.md", phase="evaluate")
    dumped = s.model_dump_json()
    revived = CvState.model_validate_json(dumped)
    assert revived.cv_path == s.cv_path
    assert revived.job_path == s.job_path
    assert revived.phase == "evaluate"


def test_hash_file_is_deterministic(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello world")
    h1 = _hash_file(p)
    h2 = _hash_file(p)
    assert h1 == h2
    assert h1 == hashlib.sha1(b"hello world").hexdigest()[:16]


def test_hash_file_missing_returns_empty(tmp_path):
    assert _hash_file(tmp_path / "nope") == ""


def test_is_available_returns_bool():
    assert isinstance(is_available(), bool)
