"""Event-driven orchestration of the CV evaluation crew.

`CvOptimizerFlow` wraps `CVOptimizerCrew` and adds `@persist` for mid-run
resumability — re-running with the same `(cv_hash, job_hash)` resumes from the
last completed step.

Usage:

    cv-optimizer flow --cv cv/sample_cv.pdf --job jobs/sample/senior_backend_engineer.md

The module imports without error if `crewai.flow` is unavailable; callers
should branch on `is_available()`.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from src.pipeline.coercion import coerce_task_output as _coerce_task_output

from pydantic import BaseModel, Field

try:
    from crewai.flow.flow import Flow, listen, persist, router, start
    _FLOW_AVAILABLE = True
except ImportError:
    _FLOW_AVAILABLE = False
    Flow = object  # type: ignore[assignment,misc]

    def _noop(*_args, **_kwargs):
        def _wrap(fn):
            return fn
        return _wrap

    start = listen = router = persist = _noop  # type: ignore[assignment]


def is_available() -> bool:
    return _FLOW_AVAILABLE


class CvState(BaseModel):
    """Resumable state for one (CV, job) pair."""

    cv_path: str = ""
    job_path: str = ""
    with_competitor: bool = False
    role_type_hint: str | None = None

    cv_hash: str = ""
    job_hash: str = ""
    started_at: float = 0.0
    phase: str = "init"

    parsed_job: dict | None = None
    parsed_cv: dict | None = None
    evaluations: dict = Field(default_factory=dict)
    consolidated: dict | None = None
    interview_prep: dict | None = None
    competitor: dict | None = None
    final_report: dict | None = None
    errors: list[str] = Field(default_factory=list)


def _hash_file(p: str | Path) -> str:
    try:
        return hashlib.sha1(Path(p).read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


_as_dict = _coerce_task_output


def _task_key(task_output: Any) -> str:
    name = (getattr(task_output, "name", None) or
            getattr(getattr(task_output, "task", None), "name", "") or
            getattr(getattr(task_output, "task", None), "description", "")[:30])
    return (name or "").lower()


_STATE_FIELD_FOR_TASK = (
    ("parse_job",     "parsed_job"),
    ("parse_cv",      "parsed_cv"),
    ("consolidate",   "consolidated"),
    ("interview",     "interview_prep"),
    ("competitor",    "competitor"),
)


if _FLOW_AVAILABLE:

    @persist
    class CvOptimizerFlow(Flow[CvState]):

        @start()
        def ingest(self) -> str:
            self.state.started_at = time.time()
            self.state.phase = "ingest"
            self.state.cv_hash = _hash_file(self.state.cv_path)
            self.state.job_hash = _hash_file(self.state.job_path)
            return "ingested"

        @listen(ingest)
        def evaluate(self, _: str) -> str:
            self.state.phase = "evaluate"
            from src.crew import CVOptimizerCrew, CompetitorPlugin

            plugins = [CompetitorPlugin()] if self.state.with_competitor else []
            crew = CVOptimizerCrew(
                role_type_hint=self.state.role_type_hint or "Practitioner",
                plugins=plugins,
            ).build()
            inputs = {
                "job_path": self.state.job_path,
                "cv_docx_path": self.state.cv_path,
            }
            try:
                result = crew.kickoff(inputs=inputs)
            except Exception as e:
                self.state.errors.append(f"crew.kickoff failed: {e!r}")
                self.state.phase = "failed"
                return "failed"

            self._record_task_outputs(result)
            self.state.final_report = _as_dict(result)
            self.state.phase = "evaluated"
            return "evaluated"

        def _record_task_outputs(self, result: Any) -> None:
            for t in getattr(result, "tasks_output", []) or []:
                key = _task_key(t)
                payload = _as_dict(t)
                for needle, field in _STATE_FIELD_FOR_TASK:
                    if needle in key:
                        setattr(self.state, field, payload)
                        break
                else:
                    if any(k in key for k in ("evaluation", "gap", "ats")):
                        self.state.evaluations[key] = payload

        @router(evaluate)
        def branch(self, _: str) -> str:
            return "abort" if self.state.phase == "failed" else "ship"

        @listen("ship")
        def ship(self) -> dict:
            self.state.phase = "shipped"
            return {
                "elapsed_seconds": round(time.time() - self.state.started_at, 2),
                "cv_hash": self.state.cv_hash,
                "job_hash": self.state.job_hash,
                "errors": self.state.errors,
                "report": self.state.final_report,
            }

        @listen("abort")
        def abort(self) -> dict:
            return {
                "elapsed_seconds": round(time.time() - self.state.started_at, 2),
                "phase": "failed",
                "errors": self.state.errors,
            }

else:

    class CvOptimizerFlow:  # type: ignore[no-redef]
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError(
                "CvOptimizerFlow requires `crewai.flow` (CrewAI >= 0.80). "
                "Run `pip install --upgrade 'crewai[anthropic]>=0.80.0'` to enable."
            )
