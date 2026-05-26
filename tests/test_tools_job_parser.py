"""Tests for the job parser tool."""

from __future__ import annotations

import json
import tempfile

from src.tools.job_parser import _split_markdown_job, parse_job_pdf


def test_parse_job_pdf_missing_file() -> None:
    result = json.loads(parse_job_pdf.run("/no/such/file.pdf"))
    assert "error" in result


def test_parse_job_pdf_txt_file() -> None:
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
        f.write("Senior Backend Engineer\nRequirements: Python, Go")
        path = f.name
    result = json.loads(parse_job_pdf.run(path))
    assert "error" not in result or result.get("raw_text") is not None


def test_split_markdown_job_extracts_title_and_url() -> None:
    md = "# Senior Go Engineer\nLink: https://jobs.acme.com/123\n\nWe are looking for..."
    title, url, body = _split_markdown_job(md)
    assert title == "Senior Go Engineer"
    assert url == "https://jobs.acme.com/123"
    assert "We are looking for" in body


def test_split_markdown_job_missing_link() -> None:
    md = "Backend Developer\n\nDescription here."
    title, url, body = _split_markdown_job(md)
    assert title == "Backend Developer"
    assert url is None
