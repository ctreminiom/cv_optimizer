"""Job posting document parser tool.

Supports PDF (via pdfplumber), plain text (.txt), and Markdown (.md) files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from crewai.tools import tool

__all__ = ["parse_job_pdf"]


@tool("parse_job_pdf")
def parse_job_pdf(pdf_path: str) -> str:
    """
    Reads a job posting file and returns extracted raw text + metadata as JSON.
    Supports PDF (via pdfplumber), plain-text (.txt) and Markdown (.md) files.
    For .txt/.md files, uses the Claude API to extract and structure the job info.

    Markdown convention (matches files under jobs/):
        Line 1 — job title
        A "Link: <url>" line — source URL of the posting
        Remaining content — job description
    """
    path = Path(pdf_path)
    if not path.exists():
        return json.dumps({"error": f"file not found: {pdf_path}"})

    ext = path.suffix.lower()

    # ── Plain-text path (.txt and .md) ────────────────────────────────────────
    if ext in (".txt", ".md"):
        raw_text = path.read_text(encoding="utf-8", errors="replace").strip()

        md_title: str | None = None
        source_url: str | None = None
        if ext == ".md":
            md_title, source_url, raw_text = _split_markdown_job(raw_text)

        structured = _extract_job_info_with_claude(raw_text)
        # The .md's first line is an authoritative title — prefer it over LLM guess.
        if md_title and not structured.get("title") or md_title:
            structured["title"] = md_title
        if source_url:
            structured["source_url"] = source_url

        return json.dumps(
            {
                "source_file": str(path),
                "page_count": 1,
                "char_count": len(raw_text),
                "raw_text": raw_text,
                **structured,  # merges title, company, etc. if Claude found them
            }
        )

    # ── PDF path ──────────────────────────────────────────────────────────────
    try:
        import pdfplumber
    except ImportError:
        return json.dumps({"error": "pdfplumber missing: pip install pdfplumber"})

    pages_text: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                pages_text.append(page.extract_text() or "")
    except Exception as e:
        return json.dumps({"error": f"failed to parse PDF: {e}"})

    full_text = "\n\n".join(pages_text).strip()
    return json.dumps(
        {
            "source_file": str(path),
            "page_count": len(pages_text),
            "char_count": len(full_text),
            "raw_text": full_text,
        }
    )


def _split_markdown_job(raw_text: str) -> tuple:
    """Split a .md job file into (title, source_url, body).

    Convention (see jobs/*.md):
        Line 1 — job title
        A "Link: <url>" line anywhere near the top — source URL
        Remaining content — job description body (passed to the LLM extractor)
    """
    lines = raw_text.splitlines()
    title: str | None = None
    source_url: str | None = None
    body_lines: list[str] = []

    for line in lines:
        s = line.strip()
        if title is None:
            if s:
                # Strip leading markdown heading hashes if present.
                title = re.sub(r"^#+\s*", "", s).strip() or None
            continue
        # Detect the "Link: <url>" line (case-insensitive, allows bold markdown).
        m = re.match(r"^\**\s*link\s*\**\s*[:\-]\s*(\S+)", s, re.IGNORECASE)
        if m and source_url is None:
            source_url = m.group(1).strip().strip("<>")
            continue
        body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return title, source_url, body


def _extract_job_info_with_claude(
    raw_text: str,
    *,
    client: Any = None,
) -> dict:
    """
    Calls the Claude API to extract structured job fields from plain text.
    Returns a dict with keys: title, company, location, modality, seniority,
    salary_range, tech_stack, ats_keywords, role_type.
    Falls back to an empty dict if the API call fails.
    """
    if client is None:
        try:
            from src.llm.client import get_default_client

            client = get_default_client()
        except Exception:
            return {}

    prompt = (
        "Extract the following fields from the job posting text below and return "
        "ONLY a valid JSON object with these keys (use null for missing fields):\n"
        "  title, company, location, modality (onsite/hybrid/remote), seniority, "
        "salary_range, role_type (snake_case token like project_manager), "
        "tech_stack (list of strings), ats_keywords (top 15 strings).\n\n"
        f"Job posting:\n{raw_text[:6000]}"
    )

    try:
        from src.settings import get_settings

        content = client.complete(
            model=get_settings().model_haiku,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        ).strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
        return json.loads(content)
    except Exception:
        return {}
