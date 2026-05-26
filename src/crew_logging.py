"""Execution-time logging for the CrewAI pipeline.

Registers a single event-bus listener that emits structured log lines as the
crew runs — task start/finish/failure, tool calls, and LLM calls — so you can
see what each agent is doing in real time instead of only the final summary.

Logs go through `src.logging_config.get_logger` (structlog when available),
honouring `LOG_LEVEL`. LLM-call lines are DEBUG (noisy); everything else is
INFO, failures are ERROR. Install once via `install_crew_logging()`.
"""
from __future__ import annotations

import time
from typing import Any

from src.logging_config import get_logger

_log = get_logger("cv_optimizer.crew")

# Module-level guard so repeated kickoffs (e.g. the resumable flow) don't
# register duplicate handlers on the global bus.
_INSTALLED = False


def _short(value: Any, limit: int = 300) -> str:
    """Render any value as a single-line, length-capped string for a log field."""
    text = value if isinstance(value, str) else repr(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _emit(level: str, event: str, **fields: Any) -> None:
    """Log `event` with `key=value` fields in a way that works for both a
    structlog logger (kwargs) and a stdlib logger (which rejects kwargs)."""
    pairs = {k: v for k, v in fields.items() if v is not None and v != ""}
    log_fn = getattr(_log, level)
    try:
        # structlog BoundLogger: render fields structurally.
        log_fn(event, **pairs)
    except TypeError:
        # stdlib logging.Logger: fold fields into the message string.
        suffix = " ".join(f"{k}={v}" for k, v in pairs.items())
        log_fn(f"{event} {suffix}".rstrip())


def install_crew_logging() -> None:
    """Subscribe to CrewAI lifecycle events and log them. Idempotent."""
    global _INSTALLED
    if _INSTALLED:
        return

    try:
        from crewai.events import crewai_event_bus
        from crewai.events.types.llm_events import (
            LLMCallCompletedEvent,
            LLMCallFailedEvent,
            LLMCallStartedEvent,
        )
        from crewai.events.types.task_events import (
            TaskCompletedEvent,
            TaskFailedEvent,
            TaskStartedEvent,
        )
        from crewai.events.types.tool_usage_events import (
            ToolUsageErrorEvent,
            ToolUsageFinishedEvent,
            ToolUsageStartedEvent,
        )
    except Exception as exc:  # pragma: no cover - depends on crewai internals
        _emit("warning", "crew_logging_unavailable", error=str(exc))
        return

    # Per-task wall-clock so completion lines can report a duration.
    started_at: dict[str, float] = {}

    @crewai_event_bus.on(TaskStartedEvent)
    def _on_task_started(_source: Any, event: TaskStartedEvent) -> None:
        if event.task_id:
            started_at[event.task_id] = time.time()
        _emit("info", 
            "task_started",
            task=event.task_name or event.task_id,
            agent=event.agent_role,
        )

    @crewai_event_bus.on(TaskCompletedEvent)
    def _on_task_completed(_source: Any, event: TaskCompletedEvent) -> None:
        elapsed = None
        if event.task_id in started_at:
            elapsed = round(time.time() - started_at.pop(event.task_id), 1)
        out = getattr(event, "output", None)
        # `output` is a TaskOutput; prefer a typed/raw summary over its repr.
        if getattr(out, "pydantic", None) is not None:
            kind, preview = type(out.pydantic).__name__, ""
        else:
            kind, preview = "text", _short(getattr(out, "raw", out) or "")
        _emit("info",
            "task_completed",
            task=event.task_name or event.task_id,
            agent=event.agent_role,
            elapsed_s=elapsed,
            output_kind=kind,
            output=preview,
        )

    @crewai_event_bus.on(TaskFailedEvent)
    def _on_task_failed(_source: Any, event: TaskFailedEvent) -> None:
        elapsed = None
        if event.task_id in started_at:
            elapsed = round(time.time() - started_at.pop(event.task_id), 1)
        _emit("error", 
            "task_failed",
            task=event.task_name or event.task_id,
            agent=event.agent_role,
            elapsed_s=elapsed,
            error=_short(getattr(event, "error", "")),
        )

    @crewai_event_bus.on(ToolUsageStartedEvent)
    def _on_tool_started(_source: Any, event: ToolUsageStartedEvent) -> None:
        _emit("info", 
            "tool_started",
            tool=event.tool_name,
            task=event.task_name,
            args=_short(getattr(event, "tool_args", "")),
        )

    @crewai_event_bus.on(ToolUsageFinishedEvent)
    def _on_tool_finished(_source: Any, event: ToolUsageFinishedEvent) -> None:
        elapsed = None
        start, finish = getattr(event, "started_at", None), getattr(event, "finished_at", None)
        if start and finish:
            try:
                elapsed = round((finish - start).total_seconds(), 2)
            except Exception:
                elapsed = None
        _emit("info", 
            "tool_finished",
            tool=event.tool_name,
            task=event.task_name,
            cached=getattr(event, "from_cache", None),
            elapsed_s=elapsed,
        )

    @crewai_event_bus.on(ToolUsageErrorEvent)
    def _on_tool_error(_source: Any, event: ToolUsageErrorEvent) -> None:
        _emit("warning", 
            "tool_error",
            tool=getattr(event, "tool_name", None),
            task=getattr(event, "task_name", None),
            error=_short(getattr(event, "error", "")),
        )

    @crewai_event_bus.on(LLMCallStartedEvent)
    def _on_llm_started(_source: Any, event: LLMCallStartedEvent) -> None:
        _emit("debug", 
            "llm_call_started",
            model=getattr(event, "model", None),
            task=event.task_name,
            agent=event.agent_role,
        )

    @crewai_event_bus.on(LLMCallCompletedEvent)
    def _on_llm_completed(_source: Any, event: LLMCallCompletedEvent) -> None:
        _emit("debug", 
            "llm_call_completed",
            model=getattr(event, "model", None),
            task=event.task_name,
            agent=event.agent_role,
        )

    @crewai_event_bus.on(LLMCallFailedEvent)
    def _on_llm_failed(_source: Any, event: LLMCallFailedEvent) -> None:
        _emit("error", 
            "llm_call_failed",
            model=getattr(event, "model", None),
            task=getattr(event, "task_name", None),
            agent=getattr(event, "agent_role", None),
            error=_short(getattr(event, "error", "")),
        )

    _INSTALLED = True
    _emit("info", "crew_logging_installed")
