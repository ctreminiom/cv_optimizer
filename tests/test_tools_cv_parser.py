"""Tests for the CV parser tool."""

from __future__ import annotations

import json

from src.tools.cv_parser import parse_cv


def test_parse_cv_unsupported_format() -> None:
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
        f.write(b"data")
        path = f.name
    try:
        result = json.loads(parse_cv.run(path))
        assert "error" in result
        assert "unsupported" in result["error"]
    finally:
        os.unlink(path)


def test_parse_cv_missing_file() -> None:
    result = json.loads(parse_cv.run("/no/such/file.docx"))
    assert "error" in result
