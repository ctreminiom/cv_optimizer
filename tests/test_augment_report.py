"""Regression tests for _augment_report_from_tasks.

Guards the fix for the bug where the two ingestion tasks (parse_job/parse_cv)
were silently dropped when CrewAI did not set TaskOutput.name to the config
key — which starved candidate_profile, the full job object, and the downstream
Skill Alignment / parsed_resume.json sections.
"""

from __future__ import annotations

from src.report.builder import augment_report as _augment_report_from_tasks


class _TaskOut:
    def __init__(self, name=None, pydantic=None, raw=None, task=None):
        self.name = name
        self.pydantic = pydantic
        self.raw = raw
        self.task = task


class _Pyd:
    """Stand-in for a CrewAI pydantic output. Class name is what the fallback
    matcher keys on, so we synthesize subclasses with the right __name__."""

    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return self._data


def _make(cls_name, data):
    return type(cls_name, (_Pyd,), {})(data)


class _Result:
    def __init__(self, tasks_output):
        self.tasks_output = tasks_output


def test_parse_job_captured_via_pydantic_class_when_name_lost():
    job = _make(
        "JobPosting",
        {
            "title": "Sr PM",
            "company": "Apply",
            "requirements": [{"text": "Asana"}],
            "tech_stack": ["Asana"],
        },
    )
    rep = _augment_report_from_tasks({}, _Result([_TaskOut(name="", pydantic=job)]))
    assert rep["job"]["requirements"] == [{"text": "Asana"}]


def test_parse_cv_captured_from_raw_json():
    cv = _TaskOut(
        name="parse_cv_task",
        pydantic=None,
        raw='```json\n{"skills": ["Jira"], "work_experience": []}\n```',
    )
    rep = _augment_report_from_tasks({}, _Result([cv]))
    assert rep["candidate_profile"]["skills"] == ["Jira"]


def test_parse_cv_captured_via_underlying_task_name_fallback():
    """TaskOutput.name empty, but the underlying Task carries the config name."""
    task = type("T", (), {"name": "parse_cv_task", "description": ""})()
    cv = _TaskOut(name="", pydantic=None, raw='{"skills": ["Asana"]}', task=task)
    rep = _augment_report_from_tasks({}, _Result([cv]))
    assert rep["candidate_profile"]["skills"] == ["Asana"]


def test_parse_job_captured_via_description_substring_fallback():
    """No name and no pydantic — recovered from a description substring."""
    task = type("T", (), {"name": "", "description": "parse_job posting into JobPosting"})()
    jt = _TaskOut(name="", pydantic=None, raw='{"requirements": [{"text": "GTM"}]}', task=task)
    rep = _augment_report_from_tasks({}, _Result([jt]))
    assert rep["job"]["requirements"] == [{"text": "GTM"}]


def test_competitor_profile_captured_when_present():
    comp = _make(
        "CompetitorProfile", {"summary": "strong rival", "differentiators": ["native Asana"]}
    )
    rep = _augment_report_from_tasks(
        {}, _Result([_TaskOut(name="competitor_simulation_task", pydantic=comp)])
    )
    assert rep["competitor_profile"]["differentiators"] == ["native Asana"]


def test_evaluations_still_list_append_without_duplication():
    ev = _make("AgentEvaluation", {"agent_role": "HR Specialist", "strengths": ["x"]})
    rep = _augment_report_from_tasks(
        {}, _Result([_TaskOut(name="hr_evaluation_task", pydantic=ev)])
    )
    assert len(rep["evaluations"]) == 1
    assert rep["evaluations"][0]["agent_role"] == "HR Specialist"
