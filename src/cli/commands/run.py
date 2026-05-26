"""CLI command handler for the `run` subcommand.

Extracted from main.py (SRP Phase 3e). No logic changes.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

from src.cli.tracker import (
    AgentInteractionTracker as _AgentInteractionTracker,
)
from src.cli.tracker import (
    print_agent_workflow_graph as _print_agent_workflow_graph,
)
from src.cli.utils import (
    classify_role_type as _classify_role_type,
)
from src.cli.utils import (
    slugify as _slugify,
)
from src.cli.utils import (
    validate_cv_path as _validate_cv_path,
)
from src.pipeline.coercion import (
    as_dict as _as_dict,
)
from src.presentation import (
    HAS_RICH as _HAS_RICH,
)
from src.presentation import (
    banner as _banner,
)
from src.presentation import (
    console as _console,
)
from src.presentation import (
    err as _err,
)
from src.presentation import (
    info as _info,
)
from src.presentation import (
    ok as _ok,
)
from src.presentation import (
    warn as _warn,
)
from src.report.builder import augment_report as _augment_report_from_tasks
from src.report.enricher import (
    prescreen_with_haiku as _prescreen_with_haiku,
)
from src.report.enricher import (
    write_prescreen_stub as _write_prescreen_stub,
)
from src.report.renderer import (
    _ensure_markdown_report,
)

__all__ = ["cmd_run"]


def _ensure_demo_files() -> Path:
    """Create cv/sample_cv.docx and jobs/sample_job.pdf if missing.
    Returns the demo job path."""
    from src.sample_data import DEMO_CV_PATH, DEMO_JOB_PDF_PATH, SAMPLE_CV_TEXT, SAMPLE_JOB_TEXT

    cv_path = Path(DEMO_CV_PATH)
    job_path = Path(DEMO_JOB_PDF_PATH)
    cv_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.parent.mkdir(parents=True, exist_ok=True)

    if not cv_path.exists():
        from docx import Document

        doc = Document()
        for line in SAMPLE_CV_TEXT.splitlines():
            doc.add_paragraph(line)
        doc.save(cv_path)
        _ok(f"Wrote sample CV: {cv_path}")

    if not job_path.exists():
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas

            c = canvas.Canvas(str(job_path), pagesize=letter)
            y = 750
            for line in SAMPLE_JOB_TEXT.splitlines():
                if y < 50:
                    c.showPage()
                    y = 750
                c.drawString(50, y, line[:95])
                y -= 14
            c.save()
            _ok(f"Wrote sample job posting PDF: {job_path}")
        except ImportError:
            txt_path = job_path.with_suffix(".txt")
            txt_path.write_text(SAMPLE_JOB_TEXT, encoding="utf-8")
            _warn(f"reportlab missing; wrote TXT instead: {txt_path}")
            return txt_path

    os.environ["DEMO_CV_PATH"] = str(cv_path)
    return job_path


# ─── Process one job ──────────────────────────────────────────────────────


def _process_one_job(
    cv_path: Path,
    job_path: Path,
    output_dir: Path,
    skip_cover_letter: bool,
    with_competitor: bool,
    mode: str,
    prescreen: bool = True,
) -> dict:
    """Run the full crew for a single job posting (.pdf, .txt, or .md).
    Uses the fingerprint cache (#15) to skip if we've processed this exact pair before."""
    from src.crew import CompetitorPlugin, CVOptimizerCrew
    from src.fingerprint import (
        compute_fingerprint,
        cv_fingerprint,
        jd_fingerprint,
        load_cached,
        save_cached,
        save_cv_parse,
        save_jd_parse,
    )

    fp = compute_fingerprint(
        cv_path, job_path, skip_cover_letter=skip_cover_letter, with_competitor=with_competitor
    )
    # Split fingerprints — stable across CV edits to OTHER fields. §3.3.
    cv_fp = cv_fingerprint(cv_path)
    jd_fp = jd_fingerprint(job_path)
    cached = load_cached(fp)
    # Staleness guard: cache entries written before the parse-capture fix lack
    # candidate_profile (and a full job), which silently empties Skill
    # Alignment, the Job Posting Reference, and parsed_resume.json. Treat those
    # as a miss so the crew re-runs and repopulates the parse outputs.
    if cached and not _as_dict(cached.get("candidate_profile") or cached.get("candidate")):
        _info(
            f"Cache hit (fingerprint {fp}) but missing parsed candidate "
            "profile — discarding stale entry and re-running the crew."
        )
        cached = None
    if cached:
        _info(
            f"Cache hit (fingerprint {fp}) — skipping crew, "
            "regenerating report from cached evaluation data …"
        )
        cached["cached"] = True
        cached["job_path"] = str(job_path)

        # Regenerate the report from cached data — re-runs the cheap
        # enrichment helpers + Haiku call so the user gets the latest
        # report format even on a cache hit (no expensive crew kickoff).
        report_path = _ensure_markdown_report(cached, output_dir, job_path, cv_path)
        if report_path:
            cached.setdefault("output_files", {})
            # report.pdf is the canonical artifact; .md is the legacy fallback.
            if str(report_path).lower().endswith(".pdf"):
                cached["output_files"]["report_pdf"] = str(report_path)
            else:
                cached["output_files"]["report_markdown"] = str(report_path)
            if _HAS_RICH:
                _console.print(
                    f"[bold green]📄 Report (from cache):[/bold green] [cyan]{report_path}[/cyan]"
                )
        return cached

    # §3.1 — Cheap Haiku pre-screen before paying for the full crew.
    prescreen_result: dict = {}
    if prescreen:
        _info("Running cheap pre-screen (Haiku) …")
        prescreen_result = _prescreen_with_haiku(cv_path, job_path)
        if not prescreen_result.get("proceed", True):
            reason = prescreen_result.get("reason", "—")
            _warn(f"Pre-screen SKIP — {reason}")
            # Build a minimal report.md stub so the folder is visible in the
            # leaderboard as "skip".
            resume_slug = _slugify(cv_path.stem, max_len=60) or "resume"
            job_slug = _slugify(job_path.stem, max_len=60) or job_path.stem
            target_dir = output_dir / resume_slug / job_slug
            md_path = _write_prescreen_stub(target_dir, job_path, cv_path, prescreen_result)
            return {
                "prescreen_skipped": True,
                "prescreen": prescreen_result,
                "cached": False,
                "fingerprint": fp,
                "job_path": str(job_path),
                "job": {"title": job_path.stem},
                "output_files": {"report_markdown": str(md_path)} if md_path else {},
                "enrichment": {
                    "status_badge": ("🔴", "Pre-screen skip", prescreen_result.get("reason", "")),
                    "decision_helper": {
                        "verdict": "❌ Skip — invest time in higher-fit roles",
                        "reason": prescreen_result.get("reason", ""),
                        "pros": [],
                        "cons": [],
                    },
                    "effort_estimate": {
                        "minutes": 0,
                        "band": "n/a",
                        "emoji": "⏭️",
                        "label": "skipped",
                    },
                    "posting_freshness": _posting_freshness(job_path),
                },
            }

    role_hint = _classify_role_type(job_path)
    _info(f"Inferred role type: {role_hint}")

    # Pre-run UX: show the user the full agent collaboration graph so they
    # can see exactly which specialists will weigh in and how the data flows.
    _print_agent_workflow_graph(
        skip_cover_letter=skip_cover_letter, with_competitor=with_competitor
    )

    inputs = {
        "cv_docx_path": str(cv_path),
        "job_path": str(job_path),
        "output_dir": str(output_dir),
        "role_type": role_hint,
        "mode": mode,
    }

    plugins = [CompetitorPlugin()] if with_competitor else []
    crew_obj = CVOptimizerCrew(
        role_type_hint=role_hint,
        plugins=plugins,
    ).build()

    # Hook a per-task callback to drive a live progress bar.
    tracker = _AgentInteractionTracker(total_tasks=len(crew_obj.tasks))
    with contextlib.suppress(Exception):
        crew_obj.task_callback = tracker.on_task_complete

    tracker.announce_start()
    crew_started = time.time()
    result = crew_obj.kickoff(inputs=inputs)
    crew_elapsed = round(time.time() - crew_started, 1)

    # Post-run UX:
    #   1) Per-task summary table (chronological)
    #   2) Workflow tree re-rendered with execution times annotated per agent
    #   3) Completion banner
    tracker.render_summary()
    tracker.render_workflow_with_timings(
        skip_cover_letter=skip_cover_letter,
        with_competitor=with_competitor,
    )
    if _HAS_RICH:
        _console.print(
            f"\n[bold green]🎉 Crew completed in {crew_elapsed}s[/bold green] — "
            f"[bold]{len(tracker.events)}/{len(crew_obj.tasks)}[/bold] "
            f"agent task(s) executed.\n"
        )

    # Assemble the JobReport deterministically from each task's structured
    # output. We deliberately do NOT ask an LLM to re-emit the whole report —
    # that copy-everything render step was the slowest call in the run and the
    # data is already in hand here.
    report: dict = _augment_report_from_tasks({}, result)
    if not report:
        # Fallback: no structured task outputs came back — keep raw for debugging.
        raw = getattr(result, "raw", None)
        report = {"raw_output": raw if isinstance(raw, str) else str(result)}

    # Generate the recommendation markdown report. The cv_proposal.docx and
    # its "Proposal Analysis & Plan" section are now produced inside
    # _ensure_markdown_report so the report can describe the proposal in-line.
    report_path = _ensure_markdown_report(report, output_dir, job_path, cv_path)
    if report_path:
        report.setdefault("output_files", {})
        # report.pdf is the canonical artifact; .md is the legacy fallback.
        if str(report_path).lower().endswith(".pdf"):
            report["output_files"]["report_pdf"] = str(report_path)
        else:
            report["output_files"]["report_markdown"] = str(report_path)
        if _HAS_RICH:
            _console.print(
                f"[bold green]📄 Recommendations:[/bold green] [cyan]{report_path}[/cyan]"
            )
    else:
        # _ensure_markdown_report swallows exceptions and writes _FAILED.pdf.
        # Mark the report so the runner reports this as a failure instead of
        # silently calling it "Finished".
        report["render_failed"] = True

    report["fingerprint"] = fp
    report["cv_fingerprint"] = cv_fp
    report["jd_fingerprint"] = jd_fp
    # Stamp the source job path so the run-summary always has a usable label
    # even when the agent's `job` dict is missing or string-typed.
    report["job_path"] = str(job_path)
    save_cached(fp, report)
    # §3.3 — Persist the per-input parse outputs so future runs can re-use
    # them even if the OTHER input changes (one-char CV edit → all jobs miss).
    try:
        cand = _as_dict(report.get("candidate_profile") or report.get("candidate"))
        if cand:
            save_cv_parse(cv_fp, cand)
        job_dict = _as_dict(report.get("job"))
        if job_dict:
            save_jd_parse(jd_fp, job_dict)
    except Exception as e:
        _warn(f"Could not save split parse caches: {e}")
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Report enrichment — pure-Python post-processing helpers + one bundled
# Haiku call. These produce the new sections that turn the .md from a
# "summary of evaluations" into a complete decision + edit guide.
# ─────────────────────────────────────────────────────────────────────────────


# ─── Scoring + decision helpers ───────────────────────────────────────────
# Implementations live in src/pipeline/scoring.py. The underscore aliases
# preserve the legacy names used at the call sites in this file.


from src.report.enricher import (  # noqa: E402
    posting_freshness as _posting_freshness,
)


def cmd_run(args: argparse.Namespace) -> int:
    if args.demo:
        pdfs = [_ensure_demo_files()]
        cv_path = Path(os.environ.get("DEMO_CV_PATH", "cv/sample_cv.docx"))
    else:
        if not args.cv:
            _err("--cv is required (or use --demo)")
            return 2
        cv_err = _validate_cv_path(args.cv)
        if cv_err:
            _err(cv_err)
            return 2
        cv_path = args.cv
        if args.job:
            if not args.job.exists():
                _err(f"--job not found: {args.job}")
                return 2
            pdfs = [args.job]
        elif args.jobs:
            if not args.jobs.is_dir():
                _err(f"--jobs is not a directory: {args.jobs}")
                return 2
            pdfs = sorted(
                list(args.jobs.glob("*.pdf"))
                + list(args.jobs.glob("*.txt"))
                + list(args.jobs.glob("*.md")),
                key=lambda p: p.name,
            )
            if args.max_jobs:
                pdfs = pdfs[: args.max_jobs]
            if not pdfs:
                _err(f"No job files (.pdf, .txt, or .md) found in {args.jobs}")
                return 2
        else:
            _err("either --job or --jobs is required (or --demo)")
            return 2

    # §2.5 — Selective re-run: only process jobs whose previous output is
    # empty / failed. Applies after the file list is loaded but before the
    # dry-run / actual processing kicks off.
    if getattr(args, "rerun_failed", False) or getattr(args, "rerun_empty", False):
        original_count = len(pdfs)
        pdfs = _filter_jobs_for_rerun(
            pdfs,
            args.output,
            cv_path,
            rerun_failed=getattr(args, "rerun_failed", False),
            rerun_empty=getattr(args, "rerun_empty", False),
        )
        _info(f"--rerun-* filter: {len(pdfs)}/{original_count} jobs need re-processing")
        if not pdfs:
            _ok("Nothing to re-run — every prior output folder is complete.")
            return 0

    if args.dry_run:
        _dry_run(cv_path, pdfs, args)
        return 0

    if not os.getenv("ANTHROPIC_API_KEY"):
        _err("ANTHROPIC_API_KEY not set in .env or environment")
        return 2

    args.output.mkdir(parents=True, exist_ok=True)
    _banner(f"CV OPTIMIZER — processing {len(pdfs)} job(s)")

    started = time.time()
    import datetime as _dt

    run_id = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = {
        "run_id": run_id,
        "started_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "cv_master": str(cv_path),
        "total_jobs_processed": len(pdfs),
        "jobs_succeeded": 0,
        "jobs_failed": 0,
        "jobs_skipped_cached": 0,
        "jobs_skipped_prescreen": 0,
        "results": [],
        "failures": [],
    }

    # §3.2 — Parallel job processing (default 1 = current sequential behaviour).
    parallel = max(1, int(getattr(args, "parallel", 1) or 1))

    def _record_result(idx: int, job_path: Path, res: dict) -> None:
        if res.get("cached"):
            summary["jobs_skipped_cached"] += 1
        if res.get("prescreen_skipped"):
            summary["jobs_skipped_prescreen"] += 1
        if res.get("render_failed"):
            # The crew finished but the report renderer crashed. Surface it
            # as a failure so the run_summary isn't misleading.
            summary["jobs_failed"] += 1
            summary["failures"].append(
                {
                    "job": str(job_path),
                    "error": "report renderer failed — see _FAILED.pdf in the job folder",
                }
            )
            summary["results"].append(res)
            _err(f"[{idx}/{len(pdfs)}] Render failed for {job_path.name} — see _FAILED.pdf")
            return
        summary["jobs_succeeded"] += 1
        summary["results"].append(res)
        _ok(f"[{idx}/{len(pdfs)}] Finished {job_path.name}")

    def _record_failure(idx: int, job_path: Path, exc: Exception) -> None:
        summary["jobs_failed"] += 1
        summary["failures"].append({"job": str(job_path), "error": str(exc)})
        _err(f"[{idx}/{len(pdfs)}] Failed processing {job_path.name}: {exc}")
        if args.verbose:
            traceback.print_exc()

    if parallel <= 1:
        # Sequential — preserves existing UX (banners, progress).
        for i, job_path in enumerate(pdfs, 1):
            _banner(f"[{i}/{len(pdfs)}]  {job_path.name}")
            try:
                res = _process_one_job(
                    cv_path=cv_path,
                    job_path=job_path,
                    output_dir=args.output,
                    skip_cover_letter=args.skip_cover_letter,
                    with_competitor=args.with_competitor,
                    mode=args.mode,
                    prescreen=getattr(args, "prescreen", True),
                )
                _record_result(i, job_path, res)
            except KeyboardInterrupt:
                _warn("Interrupted by user")
                break
            except Exception as e:
                _record_failure(i, job_path, e)
    else:
        # Parallel — job-level concurrency. I/O-bound (API calls), threads
        # are fine. Per-job banners are interleaved; we tag each line.
        import concurrent.futures as _cf

        _info(f"Running {len(pdfs)} jobs with --parallel {parallel}")
        with _cf.ThreadPoolExecutor(max_workers=parallel) as ex:
            futures = {
                ex.submit(
                    _process_one_job,
                    cv_path=cv_path,
                    job_path=jp,
                    output_dir=args.output,
                    skip_cover_letter=args.skip_cover_letter,
                    with_competitor=args.with_competitor,
                    mode=args.mode,
                    prescreen=getattr(args, "prescreen", True),
                ): (i, jp)
                for i, jp in enumerate(pdfs, 1)
            }
            for fut in _cf.as_completed(futures):
                i, jp = futures[fut]
                try:
                    _record_result(i, jp, fut.result())
                except Exception as e:
                    _record_failure(i, jp, e)

    summary["elapsed_seconds"] = round(time.time() - started, 1)
    summary_path = _write_run_summary_md(summary, args.output)
    _write_run_summary_json(summary, args.output)

    _banner("RUN COMPLETE")
    _ok(f"Succeeded : {summary['jobs_succeeded']}")
    if summary["jobs_skipped_cached"]:
        _info(f"Cache hits: {summary['jobs_skipped_cached']}")
    if summary["jobs_failed"]:
        _warn(f"Failed    : {summary['jobs_failed']}")
    if summary_path:
        _info(f"Summary   : {summary_path.resolve()}")
    _info(f"Output dir: {args.output.resolve()}")
    _info(f"Elapsed   : {summary['elapsed_seconds']} s")

    # §3.8 — open the top-N reports if requested.
    top_n = int(getattr(args, "open_top", 0) or 0)
    if top_n > 0:
        _open_top_reports(summary["results"], top_n)

    return 0 if summary["jobs_failed"] == 0 else 1


def _write_run_summary_json(summary: dict, output_dir: Path) -> Path | None:
    """Emit run_summary.json so downstream tooling can pipe results into jq /
    custom scripts without re-parsing the markdown. §3.7."""
    try:
        path = output_dir / "run_summary.json"
        # Slim down — drop the giant raw_output blobs but keep structured fields.
        slim_results = []
        for r in summary.get("results") or []:
            r = _as_dict(r) or {}
            slim_results.append(
                {
                    "job_path": r.get("job_path"),
                    "job": _as_dict(r.get("job")),
                    "cached": r.get("cached", False),
                    "prescreen_skipped": r.get("prescreen_skipped", False),
                    "fingerprint": r.get("fingerprint"),
                    "output_files": _as_dict(r.get("output_files")),
                    "enrichment": {
                        "status_badge": _as_dict(r.get("enrichment")).get("status_badge"),
                        "decision_helper": _as_dict(
                            _as_dict(r.get("enrichment")).get("decision_helper")
                        ),
                        "effort_estimate": _as_dict(
                            _as_dict(r.get("enrichment")).get("effort_estimate")
                        ),
                        "tldr": _as_dict(_as_dict(r.get("enrichment")).get("tldr")),
                        "posting_freshness": _as_dict(r.get("enrichment")).get("posting_freshness"),
                    },
                    "overall_match_score": r.get("overall_match_score"),
                    "ats_missing_keywords": _as_dict(r.get("ats_report")).get("missing_keywords"),
                    "critical_gaps": _as_dict(r.get("gap_analysis")).get("critical_gaps"),
                }
            )
        out = {**{k: v for k, v in summary.items() if k != "results"}, "results": slim_results}
        path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        return path
    except Exception as e:
        _warn(f"Could not write run_summary.json: {e}")
        return None


def _aggregate_keyword_heatmap(results: list[dict], top_n: int = 15) -> list[dict]:
    """Across all processed jobs, tally which missing ATS keywords appear in
    the most postings — so the user knows which master-CV edits unlock the
    most applications. §2.4."""
    from collections import Counter

    counter: Counter = Counter()
    samples: dict[str, list[str]] = {}
    for r in results:
        r = _as_dict(r) or {}
        ats = _as_dict(r.get("ats_report"))
        job_label = (_as_dict(r.get("job")).get("title") or Path(str(r.get("job_path", ""))).stem)[
            :40
        ]
        for kw in ats.get("missing_keywords") or []:
            if not isinstance(kw, str) or not kw.strip():
                continue
            key = kw.strip().lower()
            counter[key] += 1
            samples.setdefault(key, []).append(job_label)
    rows = []
    for key, count in counter.most_common(top_n):
        rows.append({"keyword": key, "count": count, "jobs": samples.get(key, [])[:5]})
    return rows


def _aggregate_gap_heatmap(results: list[dict], top_n: int = 10) -> list[dict]:
    """Tally critical-gap themes across all jobs so the user can see the
    structural blockers that recur. §2.4."""
    from collections import Counter

    counter: Counter = Counter()
    samples: dict[str, list[str]] = {}
    for r in results:
        r = _as_dict(r) or {}
        gap = _as_dict(r.get("gap_analysis"))
        job_label = (_as_dict(r.get("job")).get("title") or Path(str(r.get("job_path", ""))).stem)[
            :40
        ]
        for g in gap.get("critical_gaps") or []:
            if not isinstance(g, str) or not g.strip():
                continue
            # Normalize: lowercase + truncated to first 60 chars as topic key.
            key = g.strip().lower()[:60]
            counter[key] += 1
            samples.setdefault(key, []).append(job_label)
    rows = []
    for key, count in counter.most_common(top_n):
        if count >= 2:  # only surface gaps that recur
            rows.append({"gap": key, "count": count, "jobs": samples.get(key, [])[:5]})
    return rows


def _verdict_rank(verdict: str) -> int:
    """Lower = better. Used to sort the leaderboard."""
    v = (verdict or "").lower()
    if "skip" in v or "❌" in v:
        return 4
    if "only if" in v or "⚠" in v:
        return 3
    if "address gaps" in v or "but " in v:
        return 2
    if "apply" in v or "✅" in v:
        return 1
    return 5


def _leaderboard_sort_key(r: dict) -> tuple:
    """Sort key for leaderboard buckets: lower verdict rank first, then lower effort."""
    enrichment = _as_dict(_as_dict(r.get("enrichment")))
    return (
        _verdict_rank(_as_dict(enrichment.get("decision_helper")).get("verdict", "")),
        _as_dict(enrichment.get("effort_estimate")).get("minutes", 9999),
    )


def _build_leaderboard(results: list[dict]) -> list[tuple[str, list[dict]]]:
    """Bucket per-job results into priority groups for the cross-job
    leaderboard. §2.3."""
    buckets: dict[str, list[dict]] = {
        "apply_first": [],
        "apply_effort": [],
        "stretch": [],
        "skip": [],
    }
    for r in results:
        r = _as_dict(r) or {}
        enr = _as_dict(r.get("enrichment"))
        dec = _as_dict(enr.get("decision_helper"))
        eff = _as_dict(enr.get("effort_estimate"))
        rank = _verdict_rank(dec.get("verdict", ""))
        band = (eff.get("band") or "moderate").lower()
        if rank == 1 and band in ("quick", "moderate"):
            buckets["apply_first"].append(r)
        elif rank <= 2 and band != "very heavy":
            buckets["apply_effort"].append(r)
        elif rank == 3:
            buckets["stretch"].append(r)
        else:
            buckets["skip"].append(r)
    # Sort each bucket: lower verdict rank first, then lower effort minutes.
    for k in buckets:
        buckets[k].sort(key=_leaderboard_sort_key)
    return [
        ("Apply first (high fit, manageable effort)", buckets["apply_first"]),
        ("Worth applying with effort", buckets["apply_effort"]),
        ("Stretch — only with strong cover letter", buckets["stretch"]),
        ("Skip — invest elsewhere", buckets["skip"]),
    ]


def _write_run_summary_md(summary: dict, output_dir: Path) -> Path | None:
    """Write a markdown summary of the run.

    Defensive against partially-string-typed report dicts: each result `r`
    may have `r["job"]` as a JSON-encoded string when the agent failed to
    return structured output. We coerce via _as_dict before reading fields.
    """
    try:
        path = output_dir / "run_summary.pdf"
        lines: list[str] = []
        import datetime as _dt

        ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines.append("# 📊 CV Optimizer — Run Summary\n")
        lines.append(f"_Generated: {ts} · run_id: `{summary.get('run_id', '—')}`_\n")

        # ── Tracking-failure guard (§2.1) ────────────────────────────────────
        total = int(summary.get("total_jobs_processed", 0) or 0)
        succ = int(summary.get("jobs_succeeded", 0) or 0)
        fail = int(summary.get("jobs_failed", 0) or 0)
        cached = int(summary.get("jobs_skipped_cached", 0) or 0)
        if total > 0 and (succ + fail) == 0:
            lines.append(
                "> ⚠️ **Tracking failure detected**: "
                f"{total} job(s) were in scope but none were "
                "counted as succeeded, failed, or cached. Check "
                "the per-job output folders for stragglers and "
                "re-run with `--rerun-empty` to fill gaps.\n"
            )

        lines.append("---\n")
        lines.append("## Stats\n")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(f"| **Master CV** | `{summary.get('cv_master', '—')}` |")
        lines.append(f"| **Total jobs processed** | {total} |")
        lines.append(f"| **✅ Succeeded** | {succ} |")
        lines.append(f"| **🟡 Cache hits** | {cached} |")
        lines.append(f"| **⏭️ Pre-screen skipped** | {summary.get('jobs_skipped_prescreen', 0)} |")
        lines.append(f"| **❌ Failed** | {fail} |")
        lines.append(f"| **⏱️ Elapsed** | {summary.get('elapsed_seconds', 0)} s |")
        lines.append("")

        results = summary.get("results") or []

        # ── §2.3 — Cross-job leaderboard (the actual decision tool) ─────────
        if results:
            lines.append("## 🏆 Leaderboard — apply in this order\n")
            buckets = _build_leaderboard(results)
            any_rendered = False
            for label, bucket in buckets:
                if not bucket:
                    continue
                any_rendered = True
                lines.append(f"### {label}\n")
                lines.append("| Rank | Job | Verdict | Effort | Freshness | Open |")
                lines.append("|---|---|---|:-:|:-:|:-:|")
                for n, r in enumerate(bucket, 1):
                    r = _as_dict(r) or {}
                    job = _as_dict(r.get("job"))
                    title = (job.get("title") or Path(str(r.get("job_path", ""))).stem or "—")[:48]
                    company = (job.get("company") or "—")[:30]
                    enr = _as_dict(r.get("enrichment"))
                    dec = _as_dict(enr.get("decision_helper"))
                    eff = _as_dict(enr.get("effort_estimate"))
                    fresh = enr.get("posting_freshness") or "—"
                    # Strip wordy freshness down to the leading emoji + age.
                    fresh_short = fresh.split(".")[0][:24] if fresh else "—"
                    verdict = dec.get("verdict", "—")
                    eff_cell = f"{eff.get('emoji', '⚪')} {eff.get('label', '—')}" if eff else "—"
                    output_files = _as_dict(r.get("output_files"))
                    # Prefer PDF; fall back to .md for legacy cached entries.
                    report_link = (
                        output_files.get("report_pdf") or output_files.get("report_markdown") or ""
                    )
                    label = "report.pdf" if output_files.get("report_pdf") else "report.md"
                    open_cell = f"[{label}]({report_link})" if report_link else "—"
                    lines.append(
                        f"| {n} | **{title}** @ {company} | {verdict} | "
                        f"{eff_cell} | {fresh_short} | {open_cell} |"
                    )
                lines.append("")
            if not any_rendered:
                lines.append("_(No results to rank yet.)_\n")

        # ── §2.4 — Aggregate ATS-keyword heatmap ────────────────────────────
        if len(results) >= 2:
            heatmap = _aggregate_keyword_heatmap(results)
            if heatmap:
                lines.append("## 🎯 Master-CV edits with highest payoff\n")
                lines.append(
                    "_Missing ATS keywords ranked by how many job postings ask for them. "
                    "Inject these into your master CV once — they unlock multiple "
                    "applications at the same time._\n"
                )
                lines.append("| Keyword | Appears in | Example jobs |")
                lines.append("|---|:-:|---|")
                for row in heatmap:
                    n = row["count"]
                    jobs = ", ".join(row["jobs"])
                    lines.append(f"| `{row['keyword']}` | {n}/{len(results)} | {jobs} |")
                lines.append("")

            gap_hm = _aggregate_gap_heatmap(results)
            if gap_hm:
                lines.append("## 🔍 Recurring blockers across jobs\n")
                lines.append(
                    "_Critical gaps cited on 2+ postings — fix at the source rather "
                    "than working around them per-application._\n"
                )
                for row in gap_hm:
                    lines.append(f"- **{row['count']}× —** {row['gap']}")
                    if row["jobs"]:
                        lines.append(f"  - _Jobs:_ {', '.join(row['jobs'])}")
                lines.append("")

        # ── Per-job at-a-glance: detailed cards, sorted by leaderboard order ─
        if results:
            ordered: list[dict] = []
            for _label, bucket in _build_leaderboard(results) or []:
                ordered.extend(bucket)
            lines.append("## At a glance — top finding per job\n")
            for i, r in enumerate(ordered, 1):
                r = _as_dict(r) or {}
                job = _as_dict(r.get("job"))
                title = job.get("title") or Path(str(r.get("job_path", ""))).stem or "—"
                company = job.get("company") or "—"
                enr = _as_dict(r.get("enrichment"))
                dec = _as_dict(enr.get("decision_helper"))
                eff = _as_dict(enr.get("effort_estimate"))
                lines.append(f"### {i}. {title} @ {company}\n")
                if dec.get("verdict"):
                    lines.append(f"- 🤔 **Verdict:** {dec['verdict']}")
                if eff:
                    lines.append(
                        f"- ⏱️ **Effort:** {eff.get('emoji', '')} "
                        f"{eff.get('band', '')} ({eff.get('label', '')})"
                    )
                rf_found = False
                for ev in r.get("evaluations") or []:
                    ev_d = _as_dict(ev)
                    flags = [f for f in (ev_d.get("red_flags") or []) if isinstance(f, str)]
                    if flags:
                        lines.append(f"- 🚩 **{ev_d.get('agent_role', 'Reviewer')}:** {flags[0]}")
                        rf_found = True
                        break
                if not rf_found:
                    gap = _as_dict(r.get("gap_analysis"))
                    crit = [g for g in (gap.get("critical_gaps") or []) if isinstance(g, str)]
                    if crit:
                        lines.append(f"- 🚩 **Critical gap:** {crit[0]}")
                cf = _as_dict(r.get("consolidated_feedback"))
                changes = [c for c in (cf.get("prioritized_changes") or []) if isinstance(c, dict)]
                top = next(
                    (c for c in changes if (c.get("impact") or "").lower() == "high"),
                    changes[0] if changes else None,
                )
                if top:
                    lines.append(
                        f"- 📋 **Top edit:** [{top.get('change_type', 'edit')}] "
                        f"{top.get('target_section', '—')} — {top.get('description', '')}"
                    )
                ats = _as_dict(r.get("ats_report"))
                if ats.get("missing_keywords"):
                    kw = ", ".join(f"`{k}`" for k in ats["missing_keywords"][:5])
                    lines.append(f"- 🎯 **Inject keywords:** {kw}")
                output_files = _as_dict(r.get("output_files"))
                _link = output_files.get("report_pdf") or output_files.get("report_markdown")
                if _link:
                    lines.append(f"- 📄 [Open full report]({_link})")
                lines.append("")

        failures = summary.get("failures") or []
        if failures:
            lines.append("## ❌ Failures\n")
            for f in failures:
                f = _as_dict(f)
                lines.append(f"- ❌ `{f.get('job', '—')}`")
                lines.append(f"  - {f.get('error', '')}")
            lines.append("")

        # Detect existing empty folders left behind by previous runs.
        empty_folders = _detect_empty_output_folders(output_dir)
        if empty_folders:
            lines.append("## ⚠️ Empty output folders detected\n")
            lines.append(
                "_These folders exist but contain no report.md — likely "
                "silent failures from a previous run. Re-run with "
                "`--rerun-empty` to fill them._\n"
            )
            for folder in empty_folders[:20]:
                lines.append(f"- `{folder}`")
            lines.append("")

        if not results and not failures:
            lines.append("_No jobs processed in this run._\n")

        # Cross-job badge tally (kept for at-a-glance scanning).
        if len(results) >= 2:
            tally = {"🟢": 0, "🟡": 0, "🟠": 0, "🔴": 0, "⚪": 0}
            for r in results:
                enr = _as_dict(_as_dict(r).get("enrichment"))
                badge = enr.get("status_badge")
                if isinstance(badge, (list, tuple)) and badge:
                    tally[badge[0]] = tally.get(badge[0], 0) + 1
                else:
                    tally["⚪"] += 1
            line = " · ".join(f"{k} {v}" for k, v in tally.items() if v)
            if line:
                lines.append("## Cross-job badge tally\n")
                lines.append(line)
                lines.append("")

        md_text = "\n".join(lines)
        try:
            from src.pdf_renderer import write_pdf_from_markdown

            write_pdf_from_markdown(md_text, path)
        except Exception as pdf_e:
            _warn(f"Could not render run_summary.pdf, falling back to .md: {pdf_e}")
            path = output_dir / "run_summary.md"
            path.write_text(md_text, encoding="utf-8")
        return path
    except Exception as e:
        import traceback as _tb

        _warn(f"Could not write run summary markdown: {e}")
        _warn("Traceback:\n" + _tb.format_exc())
        return None


def _detect_empty_output_folders(output_dir: Path) -> list[str]:
    """Find job-output folders that exist but contain no report.pdf /
    report.md / no cv_proposal.docx — visible artifact of silent failures
    from previous runs. §2.2 / §2.5."""
    found: list[str] = []
    try:
        for resume_dir in output_dir.iterdir():
            if not resume_dir.is_dir() or resume_dir.name.startswith("."):
                continue
            for job_dir in resume_dir.iterdir():
                if not job_dir.is_dir():
                    continue
                has_pdf = (job_dir / "report.pdf").exists()
                has_md = (job_dir / "report.md").exists()
                has_proposal = (job_dir / "cv_proposal.docx").exists()
                has_failed = (job_dir / "_FAILED.pdf").exists() or (job_dir / "_FAILED.md").exists()
                if not (has_pdf or has_md) and not has_proposal and not has_failed:
                    found.append(str(job_dir.relative_to(output_dir)))
    except Exception:
        pass
    return found


def _filter_jobs_for_rerun(
    pdfs: list[Path], output_dir: Path, cv_path: Path, rerun_failed: bool, rerun_empty: bool
) -> list[Path]:
    """Keep only the jobs whose output folder is empty / failed, when
    --rerun-failed or --rerun-empty is set. §2.5."""
    if not (rerun_failed or rerun_empty):
        return pdfs
    resume_slug = _slugify(cv_path.stem, max_len=60) or "resume"
    keep: list[Path] = []
    for jp in pdfs:
        title_slug = _slugify(jp.stem, max_len=60) or jp.stem
        resume_base = output_dir / resume_slug
        candidate_folders: list[Path] = []
        if resume_base.exists():
            for sub in resume_base.iterdir():
                if not sub.is_dir():
                    continue
                if sub.name == title_slug or sub.name.startswith(title_slug + "+"):
                    candidate_folders.append(sub)
        is_missing_or_empty = False
        if not candidate_folders:
            is_missing_or_empty = True
        else:
            for f in candidate_folders:
                has_report = (f / "report.pdf").exists() or (f / "report.md").exists()
                if not has_report:
                    is_missing_or_empty = True
                    break
                if rerun_failed and ((f / "_FAILED.pdf").exists() or (f / "_FAILED.md").exists()):
                    is_missing_or_empty = True
                    break
        if is_missing_or_empty:
            keep.append(jp)
    return keep


def _open_top_reports(results: list[dict], top_n: int) -> None:
    """Open the top-N reports in the OS's default markdown viewer. §3.8."""
    if top_n <= 0 or not results:
        return
    ordered: list[dict] = []
    for _label, bucket in _build_leaderboard(results):
        ordered.extend(bucket)
    if not ordered:
        return
    try:
        import subprocess

        opener = (
            "open"
            if sys.platform == "darwin"
            else ("xdg-open" if sys.platform.startswith("linux") else "start")
        )
        for r in ordered[:top_n]:
            files = _as_dict(_as_dict(r).get("output_files"))
            # Prefer PDF (the user-facing artifact); fall back to MD.
            target = files.get("report_pdf") or files.get("report_markdown")
            if target and Path(target).exists():
                try:
                    if opener == "start":
                        os.startfile(target)  # type: ignore[attr-defined]
                    else:
                        subprocess.Popen([opener, target])
                except Exception as e:
                    _warn(f"Could not open {target}: {e}")
    except Exception as e:
        _warn(f"--open-top failed: {e}")


def _dry_run(cv_path: Path, pdfs: list[Path], args: argparse.Namespace) -> None:
    _banner("DRY RUN — pipeline plan")
    print(f"  Master CV : {cv_path}")
    print(f"  Jobs      : {len(pdfs)} PDF(s)")
    print(f"  Mode      : {args.mode}")
    print(f"  Cover     : {'SKIP' if args.skip_cover_letter else 'INCLUDE'}")
    print(f"  Competitor: {'INCLUDE (#17)' if args.with_competitor else 'skip'}")
    print()
    print("  Per job, 11 agents and up to 18 tasks will run:")
    print("    Phase 1 — Ingestion       (3 tasks, sequential)")
    print("    Phase 2 — Evaluation      (5 tasks, async-parallel — #1)")
    print("    Phase 2.5 — Tiebreaker    (#14)")
    print("    Phase 3 — Synthesis       (1 task)")
    print("    Phase 4 — Generation +    (5-7 tasks)")
    print("              Quality gates   (with retry — #3)")
    print("    Phase 5 — Output rendering")
    print()
    print(
        f"  Estimated cost: $0.30 — $0.50 per job × {len(pdfs)} = "
        f"${0.30 * len(pdfs):.2f} — ${0.50 * len(pdfs):.2f}"
    )
    print("  Run without --dry-run to execute.\n")


# ─── Subcommand: search ───────────────────────────────────────────────────
