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
import json
from typing import Any, Awaitable, Callable, Dict, List


async def _run_evaluator(name: str,
                         fn: Callable[..., Awaitable[Dict[str, Any]]],
                         **kwargs: Any) -> Dict[str, Any]:
    """Run one evaluator and tag its result with the evaluator name."""
    try:
        result = await fn(**kwargs)
        return {"name": name, "ok": True, "result": result}
    except Exception as e:
        return {"name": name, "ok": False, "error": str(e)}


async def run_phase_2_parallel(
    evaluators: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]],
    shared_inputs: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """
    Run all Phase-2 evaluators concurrently. `evaluators` maps evaluator
    name → async callable that takes shared_inputs as kwargs.

    Returns: { evaluator_name: result_dict }
    """
    coroutines = [
        _run_evaluator(name, fn, **shared_inputs)
        for name, fn in evaluators.items()
    ]
    results = await asyncio.gather(*coroutines, return_exceptions=False)
    return {r["name"]: r for r in results}


def run_phase_2(evaluators: Dict[str, Callable], shared_inputs: Dict[str, Any]
                ) -> Dict[str, Dict[str, Any]]:
    """Synchronous wrapper for callers not in an async context."""
    return asyncio.run(run_phase_2_parallel(evaluators, shared_inputs))
