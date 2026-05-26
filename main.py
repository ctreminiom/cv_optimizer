"""
main.py — CV Optimizer v2 CLI.

Subcommands:
  run        Adapt your master CV to one or more job postings.
  search     Search public job boards using your master CV (CR-focused).
  eval       Run the regression eval suite.
  cache-clear Wipe the per-run fingerprint cache.

Examples:

  # Run optimization
  python main.py run --cv cv/master.docx --jobs jobs/
  python main.py run --cv cv/master.docx --job jobs/acme_backend.pdf
  python main.py run --demo

  # Search for jobs using the master CV (13+ sources, per-opportunity .md reports)
  python main.py search --cv cv/master.docx
  python main.py search --cv cv/master.docx --location "Costa Rica" --remote
  python main.py search --cv cv/master.docx --seniority senior --max-results 30
  python main.py search --cv cv/master.docx --role "Backend Engineer,Go developer"
  python main.py search --cv cv/master.docx --keywords "kubernetes,grpc" --modality remote
  python main.py search --cv cv/master.docx --sources "linkedin,wellfound,remoteok"
  python main.py search --cv cv/master.docx --contract-type contract --min-match 60

  # Eval suite
  python main.py eval --eval-dir eval/

  # Clear cache
  python main.py cache-clear
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv(override=True)

_TRACING = None


def _bootstrap() -> None:
    """Configure logging, tracing, and CrewAI event hooks.

    Called once from main() so these side effects don't run at import time,
    which makes the module safe to import in tests and REPLs.
    """
    global _TRACING
    from src.logging_config import configure_logging
    from src.observability import init_tracing
    from src.crew_logging import install_crew_logging

    configure_logging()
    _TRACING = init_tracing()
    install_crew_logging()


# ─── Pretty printing ──────────────────────────────────────────────────────
# Implementations live in src/presentation.py. The underscore-prefixed
# aliases below preserve the legacy names used by the call sites in this
# file (`_info`, `_ok`, …).

from src.presentation import err as _err, info as _info


# ─── Command handlers ─────────────────────────────────────────────────────

from src.cli.commands.run import cmd_run
from src.cli.commands.search import cmd_search
from src.cli.commands.eval_cmd import cmd_eval, cmd_flow, cmd_cache_clear

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cv-optimizer",
        description="Multi-agent CV optimizer + job search.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # run -----------------------------------------------------------------
    p_run = sub.add_parser("run", help="Adapt CV to one or more job postings")
    p_run.add_argument("--cv", type=Path, help="Master CV (.docx or .pdf)")
    p_run.add_argument("--jobs", type=Path, help="Directory of job PDFs")
    p_run.add_argument("--job", type=Path, help="Single job PDF")
    p_run.add_argument("--output", type=Path, default=Path("output"))
    p_run.add_argument(
        "--mode", choices=["auto", "interactive"],
        default=os.getenv("DEFAULT_MODE", "auto"),
        help="auto: run end-to-end with no prompts (default). "
             "interactive: prompt for confirmation between phases.",
    )
    p_run.add_argument("--skip-cover-letter", action="store_true")
    p_run.add_argument("--with-competitor", action="store_true",
                       help="Run competitor simulation (#17)")
    p_run.add_argument("--max-jobs", type=int)
    p_run.add_argument("--demo", action="store_true")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--verbose", action="store_true")
    # §3.1 — cheap pre-screen before paying for the full crew.
    p_run.add_argument(
        "--no-prescreen", dest="prescreen", action="store_false", default=True,
        help="Disable the cheap Haiku pre-screen that skips clearly-unfit "
             "job/CV pairs before the full crew (§3.1).",
    )
    # §3.2 — job-level parallelism.
    p_run.add_argument(
        "--parallel", type=int, default=1,
        help="Run N jobs in parallel (default 1). Bounded by Anthropic rate "
             "limits — 4 is usually safe for the standard tier.",
    )
    # §2.5 — selective re-run flags.
    p_run.add_argument(
        "--rerun-failed", action="store_true",
        help="Process only jobs whose previous output folder contains "
             "_FAILED.md (or no report.md).",
    )
    p_run.add_argument(
        "--rerun-empty", action="store_true",
        help="Process only jobs whose previous output folder is missing or "
             "has no report.md.",
    )
    # §3.8 — open-after-run hook.
    p_run.add_argument(
        "--open-top", type=int, default=0,
        help="After the run, open the top N report.md files in the OS "
             "default viewer (sorted by leaderboard).",
    )
    p_run.set_defaults(func=cmd_run)

    # search --------------------------------------------------------------
    p_search = sub.add_parser(
        "search",
        help="Search public job boards using your CV (CR-focused)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Search 13+ job boards and generate per-opportunity markdown reports.

Examples:
  python main.py search --cv cv/master.docx
  python main.py search --cv cv/master.docx --location "Costa Rica" --remote
  python main.py search --cv cv/master.docx --seniority senior --max-results 30
  python main.py search --cv cv/master.docx --role "Backend Engineer,Go developer"
  python main.py search --cv cv/master.docx --keywords "kubernetes,grpc" --modality remote
  python main.py search --cv cv/master.docx --sources "linkedin,wellfound,remoteok,glassdoor"
  python main.py search --cv cv/master.docx --contract-type contract --min-match 60
  python main.py search --cv cv/master.docx --report-dir output/my_search

Available sources: linkedin, indeed_cr, glassdoor, wellfound, remoteok,
  computrabajo, hireline, getonboard, weworkremotely, tecoloco, encuentra24,
  dice, ziprecruiter
""",
    )
    p_search.add_argument("--cv", type=Path, default=None,
                          help="Your CV (.docx or .pdf)")
    p_search.add_argument("--location", default="Costa Rica",
                          help="Target location (default: Costa Rica)")
    p_search.add_argument("--seniority", default="mid",
                          choices=["junior", "mid", "senior", "lead"],
                          help="Seniority level filter")
    p_search.add_argument("--remote", action="store_true",
                          help="Filter to remote openings only (sets --modality remote)")
    p_search.add_argument("--modality",
                          choices=["remote", "hybrid", "on_site", "any"],
                          default="any",
                          help="Work modality filter (--remote overrides this)")
    p_search.add_argument("--role",
                          help="Comma-separated role keywords to override CV-extracted ones "
                               "(e.g. 'Backend Engineer,Go developer')")
    p_search.add_argument("--keywords",
                          help="Comma-separated additional search keywords "
                               "(e.g. 'kubernetes,grpc,microservices')")
    p_search.add_argument("--contract-type",
                          choices=["full_time", "contract", "part_time", "internship"],
                          help="Contract type filter")
    p_search.add_argument("--sources",
                          help="Comma-separated list of job board sources to include. "
                               "Available: linkedin, indeed_cr, glassdoor, wellfound, remoteok, "
                               "computrabajo, hireline, getonboard, weworkremotely, tecoloco, "
                               "encuentra24, dice, ziprecruiter. "
                               "Omit to include all sources.")
    p_search.add_argument("--min-match", type=int, default=0,
                          help="Minimum match score (0-100) to include in results (default: 0)")
    p_search.add_argument("--max-results", type=int, default=20,
                          help="Maximum number of results (default: 20)")
    p_search.add_argument("--report-dir", type=Path, default=None,
                          help="Directory for per-opportunity .md reports "
                               "(default: output/reports/)")
    p_search.add_argument("--output", type=Path, default=Path("output"),
                          help="Output directory for job_search_results.json (default: output/)")
    p_search.add_argument("--verbose", action="store_true")
    # ── Quality filters + retrieve→rerank pipeline flags ────────────────
    p_search.add_argument(
        "--max-age-days", type=int, default=30,
        help="Drop postings older than N days (Tavily days / Serper tbs=qdr). "
             "Set 0 to disable. Default: 30.",
    )
    p_search.add_argument(
        "--exclude",
        help="Comma-separated terms that disqualify a posting, on top of the "
             "default blocklist (internship, unpaid, volunteer, commission only).",
    )
    p_search.add_argument(
        "--exact-location", action="store_true",
        help="Require result's location to match --location (drops "
             "'Costa Rica, Florida' false positives).",
    )
    p_search.add_argument(
        "--no-rerank", dest="rerank", action="store_false", default=True,
        help="Disable the body-fetch + embedding-rerank + LLM-judge pipeline.",
    )
    p_search.add_argument(
        "--embeddings-provider", choices=["local", "voyage", "openai"],
        default="local",
        help="Backend for the rerank step. 'local' uses sentence-transformers "
             "(no API key). Default: local.",
    )
    p_search.add_argument(
        "--no-llm-judge", dest="llm_judge", action="store_false", default=True,
        help="Skip the Haiku 4-check LLM judge stage.",
    )
    p_search.set_defaults(func=cmd_search)

    # eval ----------------------------------------------------------------
    p_eval = sub.add_parser("eval", help="Run regression eval suite (#7)")
    p_eval.add_argument("--eval-dir", type=Path, default=Path("eval"))
    p_eval.add_argument("--output", type=Path, default=Path("output"))
    p_eval.set_defaults(func=cmd_eval)

    # cache-clear ---------------------------------------------------------
    p_cc = sub.add_parser("cache-clear", help="Clear fingerprint cache (#15)")
    p_cc.set_defaults(func=cmd_cache_clear)

    # flow ----------------------------------------------------------------
    # Event-driven orchestration with @persist for resumable state. Equivalent
    # to `run` for a single (CV, job) pair but resumable after a crash.
    p_flow = sub.add_parser(
        "flow",
        help="Run one (CV, job) pair via CvOptimizerFlow (resumable)",
    )
    p_flow.add_argument("--cv", type=Path, required=True)
    p_flow.add_argument("--job", type=Path, required=True)
    p_flow.add_argument("--role-type-hint", default=None)
    p_flow.add_argument("--with-competitor", action="store_true")
    p_flow.add_argument("--output", type=Path, default=Path("output"))
    p_flow.set_defaults(func=cmd_flow)

    return parser.parse_args()


def main() -> None:
    _bootstrap()
    args = parse_args()
    if args.cmd not in {"cache-clear"}:
        try:
            from src.settings import get_settings
            get_settings()  # fails fast with a readable error on missing required env
        except Exception as e:
            _err(f"Configuration error: {e}")
            sys.exit(2)
    if _TRACING.get("crewai") or _TRACING.get("langfuse"):
        active = ", ".join(name for name, on in _TRACING.items() if on)
        _info(f"Tracing: {active}")
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
