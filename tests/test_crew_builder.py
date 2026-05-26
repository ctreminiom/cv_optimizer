"""Tests for CrewBuilder protocol and plugin composition."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.crew import CompetitorPlugin, CVOptimizerCrew


def test_crew_optimizer_has_build_method() -> None:
    c = CVOptimizerCrew.__new__(CVOptimizerCrew)
    assert hasattr(c, "build")
    assert callable(c.build)


def test_crew_plugin_protocol_is_structural() -> None:
    class _FakePlugin:
        def extra_tasks(self, _crew) -> list:
            return []

    p = _FakePlugin()
    assert hasattr(p, "extra_tasks")
    assert callable(p.extra_tasks)


def test_competitor_plugin_returns_list() -> None:
    mock_crew = MagicMock()
    mock_crew._competitor_simulation_task.return_value = MagicMock()
    plugin = CompetitorPlugin()
    tasks = plugin.extra_tasks(mock_crew)
    assert isinstance(tasks, list)
    assert len(tasks) == 1
    mock_crew._competitor_simulation_task.assert_called_once()


def test_no_plugins_stored_when_omitted() -> None:
    c = CVOptimizerCrew.__new__(CVOptimizerCrew)
    c.__init__(role_type_hint="Backend", plugins=None)
    assert c._plugins == []


def test_plugins_list_is_stored() -> None:
    plugin = CompetitorPlugin()
    c = CVOptimizerCrew.__new__(CVOptimizerCrew)
    c.__init__(role_type_hint="Backend", plugins=[plugin])
    assert plugin in c._plugins


def test_agent_and_task_methods_are_private() -> None:
    # CrewAI's @CrewBase injects framework helpers — exclude those.
    _CREWAI_FRAMEWORK = {
        "map_all_agent_variables",
        "map_all_task_variables",
        "original_agents_config_path",
        "original_tasks_config_path",
    }
    public_attrs = [
        a
        for a in dir(CVOptimizerCrew)
        if not a.startswith("_")
        and a not in ("build", "crew", "agents_config", "tasks_config")
        and a not in _CREWAI_FRAMEWORK
    ]
    # Our own builder methods (e.g. "job_posting_parser_agent", "parse_job_task")
    # must not appear publicly.
    agent_or_task = [a for a in public_attrs if "agent" in a.lower() or "task" in a.lower()]
    assert agent_or_task == [], (
        f"Found public agent/task methods: {agent_or_task}. "
        "They should be prefixed with _ to signal they are internal."
    )


def test_old_boolean_flags_removed_from_init() -> None:
    import inspect

    sig = inspect.signature(CVOptimizerCrew.__init__)
    params = list(sig.parameters.keys())
    assert "skip_cover_letter" not in params
    assert "with_competitor" not in params
