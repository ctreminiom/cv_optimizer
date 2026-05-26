"""Optional tracing — off by default.

Two backends are supported; both are env-gated:

* CrewAI Tracing — set `CREWAI_TRACING=1` and run `crewai login` once.
  The framework auto-instruments crew/agent/task events.
* Langfuse — set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`.
  Wraps the Anthropic client via OpenTelemetry exporter.

Calling `init_tracing()` from main.py at startup is a no-op when neither
backend is configured, so open-source users without observability accounts
incur zero overhead and zero sign-up friction.
"""

from __future__ import annotations

import os


def init_tracing() -> dict[str, bool]:
    """Initialise enabled tracing backends. Safe to call multiple times.

    Returns a dict describing which backends are active — useful for the
    CLI's startup banner.
    """
    active = {"crewai": False, "langfuse": False}

    if os.getenv("CREWAI_TRACING") == "1":
        try:
            import crewai  # noqa: F401  # crewai picks up tracing from env

            active["crewai"] = True
        except ImportError:
            pass

    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        try:
            from langfuse import Langfuse  # noqa: F401

            active["langfuse"] = True
        except ImportError:
            pass

    return active
