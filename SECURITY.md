# Security policy

## Reporting a vulnerability

Open a [GitHub Security Advisory](https://github.com/ctreminiom/cv_optimizer/security/advisories/new) on this repository — that gives us a private channel before disclosure. Do **not** open a public issue for security-sensitive reports.

We acknowledge within 72 hours and aim to fix critical issues within 14 days.

## Supported versions

Pre-1.0: only the latest minor version receives security fixes.

## Out of scope

- Issues that require ANTHROPIC_API_KEY exfiltration via local filesystem access (the threat model assumes the user controls their machine).
- Costs incurred by misconfigured `MODEL_*` env vars or runaway agents (see `max_iter` / `max_execution_time` in `config/agents.yaml`).
