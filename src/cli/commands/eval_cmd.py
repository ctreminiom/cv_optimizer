"""CLI command handlers for `eval`, `flow`, and `cache-clear` subcommands.

Extracted from main.py (SRP Phase 3e). No logic changes.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from src.cli.commands.run import _process_one_job
from src.cli.utils import validate_cv_path as _validate_cv_path
from src.presentation import banner as _banner
from src.presentation import err as _err
from src.presentation import info as _info
from src.presentation import ok as _ok
from src.presentation import warn as _warn

__all__ = ["cmd_eval", "cmd_flow", "cmd_cache_clear"]


def cmd_eval(args: argparse.Namespace) -> int:
    from src.eval_harness import run_eval_suite

    eval_dir = args.eval_dir
    if not eval_dir.exists():
        _err(f"Eval dir not found: {eval_dir}")
        return 2

    _banner("EVAL SUITE")

    def process_fn(cv_path: Path, job_path: Path) -> dict:
        return _process_one_job(
            cv_path=cv_path,
            job_path=job_path,
            output_dir=Path("output/eval"),
            skip_cover_letter=True,
            with_competitor=False,
            mode="auto",
        )

    summary = run_eval_suite(eval_dir, process_fn)
    _banner("EVAL COMPLETE")
    _info(f"Total : {summary.total_examples}")
    _ok(f"Passed: {summary.passed}")
    if summary.failed:
        _err(f"Failed: {summary.failed}")
    _info(f"Rate  : {summary.pass_rate * 100:.1f}%")
    _info(f"Elapsed: {summary.elapsed_seconds:.1f}s")

    out = args.output / "eval_summary.json"
    args.output.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary.model_dump(), indent=2, default=str), encoding="utf-8")
    _info(f"Summary: {out.resolve()}")
    return 0 if summary.failed == 0 else 1


# ─── Subcommand: cache-clear ──────────────────────────────────────────────


def cmd_flow(args: argparse.Namespace) -> int:
    """Run one (CV, job) pair via CvOptimizerFlow with resumable state."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        _err("ANTHROPIC_API_KEY not set in .env or environment")
        return 2

    cv_err = _validate_cv_path(args.cv)
    if cv_err:
        _err(cv_err)
        return 2
    if not args.job.exists():
        _err(f"Job file not found: {args.job}")
        return 2

    try:
        from src.flow import CvOptimizerFlow, is_available
    except Exception as e:
        _err(f"Could not import CvOptimizerFlow: {e}")
        return 2

    if not is_available():
        _err(
            "crewai.flow is not available in this install. "
            "Upgrade with `pip install --upgrade 'crewai[anthropic]>=0.80.0'`."
        )
        return 2

    args.output.mkdir(parents=True, exist_ok=True)

    _banner(f"FLOW — {args.cv.name} ↔ {args.job.name}")
    flow = CvOptimizerFlow()
    started = time.time()
    try:
        result = flow.kickoff(
            inputs={
                "cv_path": str(args.cv),
                "job_path": str(args.job),
                "role_type_hint": args.role_type_hint,
                "with_competitor": bool(args.with_competitor),
            }
        )
    except Exception as e:
        _err(f"Flow raised: {e!r}")
        return 1

    elapsed = round(time.time() - started, 1)
    _ok(f"Flow finished in {elapsed}s")

    out_path = args.output / f"flow_{args.cv.stem}_{args.job.stem}.json"
    try:
        out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        _info(f"Saved: {out_path.resolve()}")
    except Exception as e:
        _warn(f"Could not write {out_path}: {e}")

    if isinstance(result, dict) and result.get("errors"):
        for err_msg in result["errors"]:
            _warn(err_msg)
        return 1
    return 0


def cmd_cache_clear(args: argparse.Namespace) -> int:
    from src.fingerprint import clear_cache

    n = clear_cache()
    _ok(f"Cleared {n} cached run(s)")
    return 0


# ─── Argument parser ──────────────────────────────────────────────────────
