"""Tests for src/cli/utils.py."""

from __future__ import annotations

from src.cli.utils import (
    classify_role_type,
    seniority_levels,
    slugify,
    validate_cv_path,
)


def test_validate_cv_path_missing_file(tmp_path):
    assert validate_cv_path(tmp_path / "nope.pdf").startswith("CV file not found")


def test_validate_cv_path_unsupported_format(tmp_path):
    bad = tmp_path / "cv.rtf"
    bad.write_text("anything")
    msg = validate_cv_path(bad)
    assert msg is not None
    assert "unsupported" in msg.lower()


def test_validate_cv_path_accepts_pdf_and_docx(tmp_path):
    for ext in (".pdf", ".docx"):
        f = tmp_path / f"cv{ext}"
        f.write_bytes(b"x")
        assert validate_cv_path(f) is None


def test_slugify_strips_punctuation_and_caps():
    assert slugify("Hello, World!") == "hello_world"
    assert slugify("Senior Go Engineer (Remote)") == "senior_go_engineer_remote"


def test_slugify_respects_max_len():
    assert len(slugify("a" * 100, max_len=10)) == 10


def test_seniority_levels_descends_to_junior():
    assert seniority_levels("senior") == ["senior", "mid", "junior"]
    assert seniority_levels("junior") == ["junior"]


def test_seniority_levels_unknown_returns_input():
    assert seniority_levels("staff") == ["staff"]
    assert seniority_levels("") == []


def test_classify_role_type_from_string():
    assert classify_role_type("Senior Backend Engineer (Go)") == "Backend Engineer"
    assert classify_role_type("Frontend React Developer") == "Frontend Engineer"
    assert classify_role_type("totally unrelated") == "Practitioner"


def test_classify_role_type_from_markdown_file(tmp_path):
    p = tmp_path / "role.md"
    p.write_text("# Senior Project Manager\n\nLooking for a project manager...")
    assert classify_role_type(p) == "Project Manager"
