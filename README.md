# CV Optimizer — CrewAI Multi-Agent Pipeline

A CrewAI multi-agent pipeline that evaluates a master CV against a target job posting and surfaces job openings on LATAM / Costa Rica boards. Every opportunity returned has an absolute URL the user can open or download.

The `run` command spins up 11 specialist agents (HR partner, hiring manager, senior practitioner, ATS optimizer, gap analyzer, coordinator, …) which debate the candidate's fit, run a tiebreaker when scores diverge, and emit a recommendation report with prioritized changes and interview prep. The `search` command parses the master CV, expands its role keywords via a synonym taxonomy, fans out across Tavily / Serper / 13 board deep-links, then runs a body-fetch → embedding-rerank → LLM-judge pipeline that filters false positives.

---

## Quick start

### Docker (recommended)

```bash
cp .env.example .env                                                # add ANTHROPIC_API_KEY
make docker-build
make docker-test                                                    # 83 unit tests
make docker-run ARGS="run --cv cv/sample_cv.pdf --job jobs/sample/senior_backend_engineer.md"
```

### Local virtualenv

```bash
make install                                                        # creates .venv + installs deps
cp .env.example .env                                                # add ANTHROPIC_API_KEY
make test                                                           # unit tests
make run-sample                                                     # full pipeline on the bundled fixtures
```

`make help` lists every target.

---

## Subcommands

| Command | Purpose |
|---|---|
| `cv-optimizer run` | Evaluate one or more job postings against a master CV — emits a recommendation report per job |
| `cv-optimizer search` | Search public job boards using the master CV; returns absolute URLs with rerank + LLM-judge filtering |
| `cv-optimizer flow` | Same evaluation as `run` but via an event-driven Flow with resumable state (`@persist`) |
| `cv-optimizer eval` | Run the regression suite against `eval/examples/` |
| `cv-optimizer cache-clear` | Wipe the run-fingerprint cache |

Examples:

```bash
# Evaluate one job
cv-optimizer run --cv cv/master.docx --job jobs/acme_backend.pdf

# Evaluate every job in a folder, 4 in parallel
cv-optimizer run --cv cv/master.docx --jobs jobs/ --parallel 4

# Search Costa Rica job boards with the full quality pipeline
cv-optimizer search --cv cv/master.docx \
  --location "Costa Rica" --exact-location \
  --max-age-days 14 --exclude "junior,bootcamp"

# Resumable single-pair run
cv-optimizer flow --cv cv/master.docx --job jobs/acme_backend.pdf
```

---

## Search-quality pipeline

The `search` subcommand runs a two-stage retrieve→rerank flow (see [src/search_pipeline.py](src/search_pipeline.py)):

```
retrieve  → search_jobs tool (Tavily / Serper / 13 board deep-links)
            applies: synonym expansion, recency filter, negative keywords,
                     cross-board dedupe, exact-location strictness
rerank    → fetch JD body via trafilatura → embedding similarity
            (local bge-small / Voyage / OpenAI — local by default, no keys)
filter    → keyword-overlap pre-filter against full JD body
judge     → Haiku 4-check LLM rubric: role / seniority / modality / location
```

Every stage degrades gracefully when its optional dep is missing — a zero-key zero-extras install still returns the deep-link fallback.

| Flag | Purpose | Default |
|---|---|---|
| `--max-age-days N` | Drop postings older than N days (Tavily `days`, Serper `tbs=qdr`) | `30` |
| `--exclude term1,term2` | Extra terms that disqualify a posting (on top of the default blocklist) | (empty) |
| `--exact-location` | Require result location to match `--location` | off |
| `--no-rerank` | Skip the body-fetch + embedding-rerank + LLM-judge pipeline | rerank on |
| `--embeddings-provider` | `local` / `voyage` / `openai` for the reranker | `local` |
| `--no-llm-judge` | Skip the Haiku 4-check judge stage | judge on |

---

## Architecture

```
                ┌─────────────────────────────────────────────────────┐
                │      CVOptimizerCrew (run subcommand)               │
Job posting  ─► │                                                     │
Master CV    ─► │  Ingestion (sequential, with task guardrails)       │
                │    Job Posting Parser     → JobPosting              │
                │    CV Parser              → CandidateProfile        │
                │                                                     │
                │  Evaluation (async-parallel via async_execution)    │
                │    HR Partner             → AgentEvaluation         │
                │    Hiring Manager         → AgentEvaluation         │
                │    Technical Specialist   → AgentEvaluation         │
                │      └─ load_domain_knowledge_base / Knowledge src  │
                │    ATS Optimizer          → ATSReport               │
                │    Gap Analyzer           → GapAnalysis             │
                │                                                     │
                │  Tiebreaker (triggered when fit scores diverge >30) │
                │    Second-Opinion task    → SecondOpinion           │
                │                                                     │
                │  Synthesis                                          │
                │    Coordinator            → ConsolidatedFeedback    │
                │                                                     │
                │  Insight generation                                 │
                │    Interview Prep         → InterviewQuestion[]     │
                │    Salary Benchmark       → SalaryBenchmark         │
                │    Competitor (opt.)      → CompetitorProfile       │
                │                                                     │
                │  Output assembly                                    │
                │    Coordinator (render)   → JobReport               │
                └─────────────────────────────────────────────────────┘
                                  │
                                  ▼
                output/{cv}_{timestamp}/
                    ├── report.md              (recommendation report)
                    ├── job_search_results.json (search subcommand only)
                    └── reports/<job>.md        (per-opportunity)
```

The pipeline produces a **recommendation report** — the user edits their own resume from the prioritized changes. The earlier auto-rewrite + humanize + verify chain is intentionally removed to eliminate fabrication / mirroring risks and halve wall-clock time.

---

## Project structure

```
cv_optimizer/
├── main.py                          # CLI entry point + remaining command bodies
├── Makefile                         # `make help` lists targets
├── Dockerfile + docker-compose.yml  # reproducible runs
├── pyproject.toml
├── requirements.txt + requirements-dev.txt
├── .env.example
│
├── src/
│   ├── crew.py                      # CVOptimizerCrew
│   ├── search_crew.py               # JobSearchCrew
│   ├── flow.py                      # CvOptimizerFlow — @persist + @start/@listen/@router
│   ├── tools.py                     # CrewAI tools (parse_job_pdf, search_jobs, …)
│   ├── models.py                    # Pydantic schemas
│   ├── guardrails.py                # function-based task guardrails
│   ├── settings.py                  # pydantic-settings — fail-fast env validation
│   ├── logging_config.py            # structlog (JSON in CI / console in TTY)
│   ├── observability.py             # optional CrewAI Tracing / Langfuse hooks
│   ├── search_pipeline.py           # body fetch → embed rerank → keyword → LLM judge
│   ├── role_taxonomy.py             # query expansion via config/role_taxonomy.yaml
│   ├── knowledge.py                 # JSONKnowledgeSource wrapper + embedder config
│   ├── presentation.py              # Rich-backed CLI helpers
│   ├── cli/utils.py                 # validate_cv_path, slugify, classify_role_type, …
│   ├── pipeline/
│   │   ├── coercion.py              # as_dict / as_list / as_list_of_dicts
│   │   ├── url_filters.py           # URL + content classifiers used by `search`
│   │   └── scoring.py               # skill matrix, decision helper, pre-submission checklist
│   ├── cache_control.py             # prompt-caching helpers
│   ├── context_window.py            # per-task CV slicing
│   ├── memory.py                    # SQLite store for interactive decisions
│   ├── fingerprint.py               # per-input (CV, job) cache
│   ├── eval_harness.py              # regression suite runner
│   └── knowledge_bases/             # curated per-role JSON (backend, frontend, data, PM, devops)
│
├── config/
│   ├── agents.yaml                  # agent personas + per-agent limits
│   ├── tasks.yaml                   # task descriptions + expected outputs
│   └── role_taxonomy.yaml           # canonical role → synonyms (for query expansion)
│
├── tests/                           # 83 unit tests
├── eval/examples/                   # (CV, job, expected.json) regression triples
├── cv/    jobs/    output/    cache/    private/  (gitignored)
│
└── scripts/build_sample_fixtures.py
```

---

## Configuration

`.env` (see [`.env.example`](.env.example) for the full list):

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API key — Claude.ai Pro/Max does NOT include API credits |
| `MODEL_HAIKU` / `MODEL_SONNET` | | Override model IDs |
| `TAVILY_API_KEY` | for live search | Deep-web search across job boards |
| `SERPER_API_KEY` | for live search | Google Jobs vertical |
| `OPENAI_API_KEY` / `VOYAGE_API_KEY` | | Alternative embedding backends for the reranker |
| `CREW_MEMORY` | | Set `=1` to enable CrewAI memory + per-agent Knowledge sources |
| `CREW_EMBEDDER_PROVIDER` | | `huggingface` (default, local), `openai`, or `voyageai` |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | | Enable Langfuse tracing |
| `CREWAI_TRACING` | | Set `=1` to enable CrewAI Tracing (requires `crewai login` once) |
| `LOG_LEVEL` | | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

Settings are loaded once at startup via [src/settings.py](src/settings.py) and fail fast with a readable error if a required key is missing.

---

## Development

```bash
make install        # create .venv + install runtime + dev deps
make install-hooks  # install pre-commit (detect-secrets, ruff, gitleaks staging)
make test           # pytest -q tests/      (83 tests)
make lint           # ruff check + ruff format --check
make format         # ruff --fix + ruff format
make ci             # lint + test (same as GitHub Actions)
make secrets        # gitleaks + detect-secrets scan
make fixtures       # regenerate cv/sample_cv.pdf + eval/examples/sample/
make clean          # remove build caches
make clean-all      # also clean output/, cache/, .venv
```

Inside Docker:

```bash
make docker-build   # docker compose build
make docker-test    # run pytest inside the image
make docker-run ARGS="run --cv cv/sample_cv.pdf --job jobs/sample/senior_backend_engineer.md"
make docker-shell   # interactive bash with sources mounted
```

The Dockerfile uses `python:3.12-slim`, runs as a non-root `app` user, and exposes the CLI via `ENTRYPOINT ["python", "main.py"]`. The compose `dev` service mounts your source tree so code changes apply without rebuilding.

---

## Patterns worth copying

If you're building your own CrewAI project, several things in this repo are deliberate and reusable:

- **Prompt caching** ([src/cache_control.py](src/cache_control.py)) — agent personas use a 1h cache TTL, per-run CandidateProfile / JobPosting use 5m. Cuts input tokens 30–50% on multi-job runs.
- **Per-input fingerprint cache** ([src/fingerprint.py](src/fingerprint.py)) — separate hashes for CV and JD so re-running with the same CV against a new posting reuses the parsed CandidateProfile.
- **Function-based guardrails** ([src/guardrails.py](src/guardrails.py)) — task-level validation that reuses pre-existing tool functions (`detect_ai_smell`, `detect_mirroring`, `compute_keyword_match`) instead of duplicating the logic.
- **Event-driven Flow with `@persist`** ([src/flow.py](src/flow.py)) — `CvOptimizerFlow` wraps the Crew with resumable state. After a crash, re-running with the same `(cv_hash, jd_hash)` resumes from the last completed step.
- **Strategy pattern for embedders** ([src/search_pipeline.py](src/search_pipeline.py)) — `Embedder` Protocol + registry so adding a new backend means one class.

---

## Deliberate choices

These deviate from CrewAI defaults; they are not bugs:

- **`allow_delegation: false` on every agent.** The coordinator triggers a dedicated second-opinion task when Phase 2 scores diverge >30 pts; this is cheaper and more predictable than free-form delegation.
- **CrewAI memory is opt-in.** Set `CREW_MEMORY=1` to enable. When on, the embedder defaults to a local `sentence-transformers` model so no OpenAI key is required (override with `CREW_EMBEDDER_PROVIDER=openai|voyage`). The interactive-decisions store in [src/memory.py](src/memory.py) stays separate by design.
- **No CV rewriter in the active pipeline.** The previous auto-rewrite + humanize + verify chain is removed; the user edits their own resume using the recommendation report. Eliminates a class of fabrication / mirroring risks and roughly halves wall-clock time.

---

## Costs

Order-of-magnitude per command, Anthropic API only:

| Operation | Approx. cost |
|---|---|
| `run` / `flow` — 1 job (full pipeline) | $0.30 – $0.50 |
| `run` / `flow` — 1 job (cache hit) | $0 |
| `run` — 20 jobs | $6 – $10 |
| `search` (no rerank) | $0.05 – $0.15 |
| `search` (with LLM judge, 10 top-K) | $0.10 – $0.30 |

A Claude.ai Pro/Max subscription does **not** include API credits — they're billed separately via console.anthropic.com.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, test conventions, and PR guidelines. Security reports → [SECURITY.md](SECURITY.md).
