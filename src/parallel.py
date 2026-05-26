"""
parallel.py — Recommendation #1.

Runs the four Phase-2 evaluators (HR, Hiring Manager, Technical, ATS)
plus the Gap Analyzer concurrently. They all consume the same Phase-1
output (JobPosting + CandidateProfile) so they have no inter-dependencies.

In CrewAI's sequential process this would block. We bypass the crew for
this phase and call each agent's underlying LLM directly, then feed the
results back into the crew for synthesis.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


async def _run_evaluator(
    name: str, fn: Callable[..., Awaitable[dict[str, Any]]], **kwargs: Any
) -> dict[str, Any]:
    """Run one evaluator and tag its result with the evaluator name."""
    try:
        result = await fn(**kwargs)
        return {"name": name, "ok": True, "result": result}
    except Exception as e:
        return {"name": name, "ok": False, "error": str(e)}


async def run_phase_2_parallel(
    evaluators: dict[str, Callable[..., Awaitable[dict[str, Any]]]],
    shared_inputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    Run all Phase-2 evaluators concurrently. `evaluators` maps evaluator
    name → async callable that takes shared_inputs as kwargs.

    Returns: { evaluator_name: result_dict }
    """
    coroutines = [_run_evaluator(name, fn, **shared_inputs) for name, fn in evaluators.items()]
    results = await asyncio.gather(*coroutines, return_exceptions=False)
    return {r["name"]: r for r in results}


def run_phase_2(
    evaluators: dict[str, Callable], shared_inputs: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Synchronous wrapper for callers not in an async context."""
    return asyncio.run(run_phase_2_parallel(evaluators, shared_inputs))
