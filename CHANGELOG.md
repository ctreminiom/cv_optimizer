# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed
- Salary benchmark feature: `fetch_salary_benchmark` tool, `salary_benchmark_task`, the `SalaryBenchmark` model, the `JobReport.salary_benchmark` field, and the `--skip-salary` / `with_salary` flags. The task's LLM call could hang the `run` pipeline; the Compensation Reference section now shows only the posting's stated salary range.

### Added
- Resumable single-pair runs via `CvOptimizerFlow` and the new `cv-optimizer flow` subcommand.
- Search-quality pipeline: trafilatura body fetch, embedding rerank (local / Voyage / OpenAI), keyword filter against the full body, and a Haiku 4-check LLM judge. Activated by default in `cv-optimizer search`; disable with `--no-rerank`.
- Search CLI flags: `--max-age-days`, `--exclude`, `--exact-location`, `--no-rerank`, `--embeddings-provider`, `--no-llm-judge`.
- Role-synonym taxonomy ([config/role_taxonomy.yaml](config/role_taxonomy.yaml)) for query expansion and judge scoring.
- Cross-board dedupe by normalized `(title + company + city)` on top of URL-based dedup.
- Opt-in CrewAI memory and per-agent JSON knowledge sources via `CREW_MEMORY=1` (local `sentence-transformers` embedder by default).
- Task-level guardrails on parse / consolidate steps, with `guardrail_max_retries`.
- Per-agent execution limits in [config/agents.yaml](config/agents.yaml) (`max_iter`, `max_execution_time`, `max_retry_limit`, `respect_context_window`); `reasoning=true` on the three judgment-heavy agents.
- Tenacity-backed retries on Tavily and Serper calls.
- Structured logging (`src/logging_config.py`), pydantic-settings config (`src/settings.py`), and optional CrewAI Tracing / Langfuse hooks (`src/observability.py`).
- Open-source scaffolding: `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.pre-commit-config.yaml`, GitHub Actions CI (ruff, pytest, gitleaks), issue/PR templates, Dependabot.
- `Dockerfile` + `.dockerignore` for reproducible runs.
- Sample fixtures: `cv/sample_cv.pdf`, `jobs/sample/*.md`, `eval/examples/sample/` (synthetic data, safe to ship).
- Unit-test suite under `tests/` (35 tests).

### Changed
- `main.py` now configures logging and tracing at import time and validates required env via `Settings` at startup.
- Presentation helpers extracted to `src/presentation.py`; legacy `_info`/`_ok`/`_warn`/`_err`/`_banner` aliases preserved in `main.py`.
- `salary_benchmark_task` uses `inject_date=True` so cached outputs surface staleness.
- Search `--min-match` semantics: still post-filter, now applied against the fetched JD body when the rerank pipeline is active.

### Security
- Scrubbed a leaked Anthropic API key from `.env.example` (rotate the key separately — the value remains in git history).
- Moved real CVs and job postings to a gitignored `private/` directory; only synthetic samples ship.

### Removed
- `extract_voice_task`, `rewrite_cv_task`, `humanize_cv_task`, `humanize_retry_task`, `mirroring_check_task`, `verification_task`, `cover_letter_task` from the active pipeline (kept in `config/tasks.yaml` for reference; the run command emits a recommendation report rather than an adapted CV).

## [0.1.0] — pre-release

Initial private snapshot, single-user CLI.
