# cv-optimizer dev tasks.
# Run `make help` to list available targets.

PYTHON  ?= python3
VENV    ?= .venv
VENV_PY := $(VENV)/bin/python
PIP     := $(VENV_PY) -m pip
PYTEST  := $(VENV_PY) -m pytest
RUFF    := $(VENV_PY) -m ruff

SAMPLE_CV    ?= cv/sample_cv.pdf
SAMPLE_JOB   ?= jobs/sample/senior_backend_engineer.md

DOCKER_IMAGE ?= cv-optimizer:latest

.DEFAULT_GOAL := help

# ── Help ────────────────────────────────────────────────────────────────────
.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} \
	     /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' \
	     $(MAKEFILE_LIST) | sort

# ── Virtualenv + install ───────────────────────────────────────────────────
$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)

.PHONY: install
install: $(VENV)/bin/activate ## Install runtime + dev deps into .venv
	$(PIP) install -U pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt

.PHONY: install-runtime
install-runtime: $(VENV)/bin/activate ## Install runtime deps only
	$(PIP) install -U pip
	$(PIP) install -r requirements.txt

.PHONY: install-hooks
install-hooks: install ## Install pre-commit hooks
	$(VENV_PY) -m pre_commit install

# ── Quality gates ──────────────────────────────────────────────────────────
.PHONY: lint
lint: ## Run ruff lint + format check
	$(RUFF) check src/ main.py tests/ scripts/
	$(RUFF) format --check src/ main.py tests/ scripts/

.PHONY: format
format: ## Auto-format with ruff
	$(RUFF) check --fix src/ main.py tests/ scripts/
	$(RUFF) format src/ main.py tests/ scripts/

.PHONY: test
test: ## Run the pytest suite
	PYTHONPATH=. $(PYTEST) -q tests/

.PHONY: test-verbose
test-verbose: ## Run pytest with -v
	PYTHONPATH=. $(PYTEST) -v tests/

.PHONY: secrets
secrets: ## Run secret scanners locally
	@command -v gitleaks >/dev/null && gitleaks detect --no-banner --redact || \
	  echo "  gitleaks not installed — skipping (brew install gitleaks)"
	@$(VENV_PY) -m detect_secrets scan --all-files > .secrets.scan && \
	  echo "  detect-secrets scan written to .secrets.scan"

.PHONY: ci
ci: lint test ## What CI runs: lint + tests

# ── Sample fixtures ────────────────────────────────────────────────────────
.PHONY: fixtures
fixtures: ## Regenerate sample CV / job / eval fixtures
	PYTHONPATH=. $(VENV_PY) scripts/build_sample_fixtures.py

# ── App invocation ─────────────────────────────────────────────────────────
.PHONY: run-sample
run-sample: ## Run the pipeline on the bundled sample data
	PYTHONPATH=. $(VENV_PY) main.py run --cv $(SAMPLE_CV) --job $(SAMPLE_JOB)

.PHONY: search-sample
search-sample: ## Run search with the sample CV (requires TAVILY_API_KEY + SERPER_API_KEY)
	PYTHONPATH=. $(VENV_PY) main.py search --cv $(SAMPLE_CV) --max-results 10

.PHONY: flow-sample
flow-sample: ## Run the resumable Flow on the sample data
	PYTHONPATH=. $(VENV_PY) main.py flow --cv $(SAMPLE_CV) --job $(SAMPLE_JOB)

.PHONY: eval
eval: ## Run the regression eval suite
	PYTHONPATH=. $(VENV_PY) main.py eval

# ── Docker ─────────────────────────────────────────────────────────────────
.PHONY: docker-build
docker-build: ## Build the Docker image
	docker compose build

.PHONY: docker-test
docker-test: ## Run the pytest suite inside Docker
	docker compose run --rm test

.PHONY: docker-run
docker-run: ## Run the CLI inside Docker (pass ARGS=…)
	docker compose run --rm cli $(ARGS)

.PHONY: docker-shell
docker-shell: ## Open an interactive bash shell with sources mounted
	docker compose run --rm dev

.PHONY: docker-clean
docker-clean: ## Remove the built image and stop containers
	docker compose down --remove-orphans
	-docker image rm $(DOCKER_IMAGE)

# ── Housekeeping ───────────────────────────────────────────────────────────
.PHONY: clean
clean: ## Remove build caches and temp files (not output/ or cache/)
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

.PHONY: clean-all
clean-all: clean ## Also remove generated outputs, run caches, and the venv
	rm -rf output/* cache/* .venv

.PHONY: deps-upgrade
deps-upgrade: ## Upgrade dev tooling pins (ruff, pytest, pre-commit, detect-secrets)
	$(PIP) install -U ruff pytest pre-commit detect-secrets
