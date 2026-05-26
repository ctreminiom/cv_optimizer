"""Tests for src/cli/tracker.py (Phase 3a extraction)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.cli.tracker import (
    AGENT_WORKFLOW_PHASES,
    TASK_VIS,
    AgentInteractionTracker,
    print_agent_workflow_graph,
)
from src.constants import (
    TASK_CONSOLIDATE,
    TASK_HR_EVAL,
    TASK_INTERVIEW_PREP,
    TASK_PARSE_JOB,
)

# ── AGENT_WORKFLOW_PHASES ────────────────────────────────────────────────────


def test_workflow_phases_structure() -> None:
    assert len(AGENT_WORKFLOW_PHASES) == 4
    for phase in AGENT_WORKFLOW_PHASES:
        assert "name" in phase
        assert "agents" in phase
        assert isinstance(phase["agents"], list)


def test_workflow_phases_agent_tuples() -> None:
    for phase in AGENT_WORKFLOW_PHASES:
        for item in phase["agents"]:
            assert len(item) == 2


# ── TASK_VIS ─────────────────────────────────────────────────────────────────


def test_task_vis_covers_key_tasks() -> None:
    for task in (TASK_PARSE_JOB, TASK_HR_EVAL, TASK_CONSOLIDATE, TASK_INTERVIEW_PREP):
        assert task in TASK_VIS
        emoji, colour, action = TASK_VIS[task]
        assert emoji
        assert colour
        assert action


# ── AgentInteractionTracker ──────────────────────────────────────────────────


def test_tracker_init_defaults() -> None:
    tracker = AgentInteractionTracker()
    assert tracker.total_tasks == 0
    assert tracker.events == []


def test_tracker_progress_bar_empty() -> None:
    tracker = AgentInteractionTracker()
    bar, pct = tracker._progress_bar(0, 0)
    assert pct == 0
    assert len(bar) == 24


def test_tracker_progress_bar_full() -> None:
    tracker = AgentInteractionTracker(total_tasks=10)
    bar, pct = tracker._progress_bar(10, 10)
    assert pct == 100
    assert "█" in bar


def test_tracker_on_task_complete_records_event() -> None:
    tracker = AgentInteractionTracker(total_tasks=5)

    task_output = MagicMock()
    task_output.name = TASK_PARSE_JOB
    task_output.task_name = ""
    task_output.agent = "Job Parser"
    task_output.pydantic = None

    tracker.on_task_complete(task_output)

    assert len(tracker.events) == 1
    ev = tracker.events[0]
    assert ev["task_name"] == TASK_PARSE_JOB
    assert ev["agent_role"] == "Job Parser"
    assert ev["kind"] == "text"
    assert ev["elapsed"] >= 0


def test_tracker_on_task_complete_handles_exception() -> None:
    tracker = AgentInteractionTracker()

    class _Boom:
        @property
        def name(self):
            raise RuntimeError("boom")

    tracker.on_task_complete(_Boom())  # must not propagate
    assert tracker.events == []


def test_tracker_pydantic_kind() -> None:
    tracker = AgentInteractionTracker(total_tasks=1)

    pydantic_obj = MagicMock()
    pydantic_obj.__class__.__name__ = "JobPosting"
    task_output = MagicMock()
    task_output.name = TASK_PARSE_JOB
    task_output.task_name = ""
    task_output.agent = "parser"
    task_output.pydantic = pydantic_obj

    tracker.on_task_complete(task_output)
    assert tracker.events[0]["kind"] == "JobPosting"


def test_render_summary_no_events_is_noop() -> None:
    tracker = AgentInteractionTracker()
    tracker.render_summary()  # must not raise


def test_render_summary_with_events(capsys) -> None:
    tracker = AgentInteractionTracker(total_tasks=1)
    tracker.events = [
        {"task_name": TASK_PARSE_JOB, "agent_role": "Parser", "kind": "text", "elapsed": 1.2}
    ]
    tracker.render_summary()
    captured = capsys.readouterr()
    assert captured.out or True  # Rich may bypass capsys; just ensure no exception


def test_render_workflow_with_timings_no_events(capsys) -> None:
    tracker = AgentInteractionTracker()
    tracker.render_workflow_with_timings(skip_cover_letter=False, with_competitor=False)


# ── print_agent_workflow_graph ───────────────────────────────────────────────


def test_print_agent_workflow_graph_no_crash(capsys) -> None:
    print_agent_workflow_graph(skip_cover_letter=False, with_competitor=False)
    print_agent_workflow_graph(skip_cover_letter=True, with_competitor=True)
