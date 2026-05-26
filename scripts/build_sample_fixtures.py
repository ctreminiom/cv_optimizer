"""Generate the public sample fixtures:

  cv/sample_cv.pdf                                    — from cv/sample_cv.md
  eval/examples/sample/cv.pdf                         — same file (symlink target)
  eval/examples/sample/job.pdf                        — from jobs/sample/senior_backend_engineer.md
  eval/examples/sample/expected.json                  — pre-seeded EvalExample

Run with:
    python scripts/build_sample_fixtures.py

Only writes to fixture paths under cv/, jobs/, and eval/examples/sample/.
Intended for CI bootstrap and the README walkthrough — not user data.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent


def _styles() -> dict:
    base = getSampleStyleSheet()
    body = base["BodyText"]
    body.spaceAfter = 4
    return {
        "h1": ParagraphStyle("h1", parent=base["Heading1"], spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], spaceAfter=4),
        "body": body,
        "bullet": ParagraphStyle("bullet", parent=body, leftIndent=18, bulletIndent=6),
    }


def render_markdown_to_pdf(md_path: Path, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    flowables: list = []
    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            flowables.append(Paragraph(line[2:], styles["h1"]))
        elif line.startswith("## "):
            flowables.append(Paragraph(line[3:], styles["h2"]))
        elif line.startswith("### "):
            flowables.append(Paragraph(line[4:], styles["h3"]))
        elif line.startswith("- "):
            flowables.append(Paragraph(f"• {line[2:]}", styles["bullet"]))
        elif line.startswith("> "):
            continue  # skip quote blocks
        elif line.strip():
            flowables.append(Paragraph(line, styles["body"]))
        else:
            flowables.append(Spacer(1, 6))

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    doc.build(flowables)


def _build_expected_json() -> dict:
    return {
        "name": "sample",
        "cv_path": "eval/examples/sample/cv.pdf",
        "job_path": "eval/examples/sample/job.pdf",
        "expected_match_score_min": 55,
        "expected_match_score_max": 95,
        "must_include_keywords": ["go", "postgresql", "kafka", "distributed"],
        "must_avoid_phrases": ["leveraged synergies", "results-driven"],
        "notes": (
            "Synthetic example: the Jane Doe sample CV against the Acme Cloud "
            "Senior Backend Engineer posting. Expected to score in the mid-high "
            "range — the CV's Go/PostgreSQL/Kafka experience maps cleanly to "
            "the posting's must-haves."
        ),
    }


def main() -> int:
    cv_md = ROOT / "cv" / "sample_cv.md"
    cv_pdf = ROOT / "cv" / "sample_cv.pdf"
    job_md = ROOT / "jobs" / "sample" / "senior_backend_engineer.md"
    eval_dir = ROOT / "eval" / "examples" / "sample"

    if not cv_md.exists():
        print(f"missing source: {cv_md}")
        return 1
    if not job_md.exists():
        print(f"missing source: {job_md}")
        return 1

    render_markdown_to_pdf(cv_md, cv_pdf)
    print(f"wrote {cv_pdf}")

    eval_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cv_pdf, eval_dir / "cv.pdf")
    render_markdown_to_pdf(job_md, eval_dir / "job.pdf")
    (eval_dir / "expected.json").write_text(
        json.dumps(_build_expected_json(), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {eval_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
