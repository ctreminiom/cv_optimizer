# Contributing

Thanks for your interest! This project is in **alpha** — APIs and CLI flags will change.

## Development setup

```bash
git clone https://github.com/<owner>/cv_optimizer.git
cd cv_optimizer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
cp .env.example .env  # add your ANTHROPIC_API_KEY
```

## Running the pipeline

```bash
cv-optimizer run \
  --cv cv/sample_cv.pdf \
  --job jobs/sample/senior_backend_engineer.md
```

## Tests

```bash
pytest -q tests/        # unit tests
python -m cv_optimizer eval   # full-pipeline regression (uses eval/examples/)
```

## Style

- `ruff check .` and `ruff format .` — both run in pre-commit and CI.
- No comments unless the WHY is non-obvious.
- Public functions / Pydantic models get one-line docstrings.

## Personal data — never commit

The `private/` folder is gitignored and meant for your own CVs / job postings. Anything in `cv/*.pdf` is also gitignored (except `cv/sample_cv.pdf`). Run `gitleaks detect` before opening a PR.

## PRs

- Branch from `main`, open a PR, fill out the template.
- CI must pass (lint, tests, gitleaks).
- One logical change per PR. If you're tempted to make "while we're in there" cleanups, open a separate PR.
