"""
eval_harness.py — Recommendation #7.

Runs the full pipeline against a curated set of (CV, job, expectations)
triples and reports pass/fail per example. Triggered by:

    python main.py eval --eval-dir eval/

Each example lives at eval/examples/<name>/ with:
  - cv.docx         — the candidate CV
  - job.pdf         — the target job posting
  - expected.json   — EvalExample schema (score range, must-include words)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.models import EvalExample, EvalRunResult, EvalSummary


def discover_examples(eval_dir: Path) -> list[EvalExample]:
    """Scan eval/examples/ for example folders."""
    examples_dir = eval_dir / "examples"
    if not examples_dir.exists():
        return []

    examples: list[EvalExample] = []
    for sub in sorted(examples_dir.iterdir()):
        if not sub.is_dir():
            continue
        expected_file = sub / "expected.json"
        if not expected_file.exists():
            continue
        try:
            data = json.loads(expected_file.read_text())
            data.setdefault("name", sub.name)
            data.setdefault("cv_path", str(sub / "cv.docx"))
            data.setdefault("job_path", str(sub / "job.pdf"))
            examples.append(EvalExample(**data))
        except Exception as e:
            print(f"  ⚠ skipping {sub.name}: {e}")
    return examples


def run_one_example(example: EvalExample, process_fn) -> EvalRunResult:
    """
    Run the full pipeline on a single example and verify expectations.
    `process_fn(cv_path, job_path)` should return a JobReport-like dict.
    """
    start = time.time()
    issues: list[str] = []

    try:
        report = process_fn(Path(example.cv_path), Path(example.job_path))
    except Exception as e:
        return EvalRunResult(
            example_name=example.name,
            passed=False,
            actual_match_score=0,
            issues=[f"pipeline failure: {e}"],
            elapsed_seconds=time.time() - start,
        )

    score = report.get("overall_match_score", 0)

    # Score range check
    if not (example.expected_match_score_min <= score <= example.expected_match_score_max):
        issues.append(
            f"match_score={score} outside expected "
            f"[{example.expected_match_score_min}, {example.expected_match_score_max}]"
        )

    # Adapted CV must include certain keywords
    adapted_cv_text = json.dumps(report.get("adapted_cv", {})).lower()
    for kw in example.must_include_keywords:
        if kw.lower() not in adapted_cv_text:
            issues.append(f"adapted CV missing required keyword: {kw}")

    # Adapted CV must NOT include forbidden phrases
    for phrase in example.must_avoid_phrases:
        if phrase.lower() in adapted_cv_text:
            issues.append(f"adapted CV contains forbidden phrase: {phrase}")

    # Quality gates must all pass
    if not report.get("authenticity_report", {}).get("passes"):
        issues.append("authenticity gate failed")
    if not report.get("verification_report", {}).get("passes"):
        issues.append("verification gate failed")

    return EvalRunResult(
        example_name=example.name,
        passed=len(issues) == 0,
        actual_match_score=score,
        issues=issues,
        elapsed_seconds=time.time() - start,
    )


def run_eval_suite(eval_dir: Path, process_fn) -> EvalSummary:
    """Run every example and return an aggregate EvalSummary."""
    start = time.time()
    examples = discover_examples(eval_dir)
    if not examples:
        return EvalSummary(
            total_examples=0, passed=0, failed=0, pass_rate=0.0, results=[], elapsed_seconds=0.0
        )

    results: list[EvalRunResult] = []
    for ex in examples:
        print(f"\n── Running {ex.name} ──")
        r = run_one_example(ex, process_fn)
        status = "✓ PASS" if r.passed else "✗ FAIL"
        print(f"  {status}  score={r.actual_match_score}  ({r.elapsed_seconds:.1f}s)")
        for issue in r.issues:
            print(f"    • {issue}")
        results.append(r)

    passed = sum(1 for r in results if r.passed)
    return EvalSummary(
        total_examples=len(results),
        passed=passed,
        failed=len(results) - passed,
        pass_rate=round(passed / len(results), 3),
        results=results,
        elapsed_seconds=time.time() - start,
    )
