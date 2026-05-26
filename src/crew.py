"""CrewAI orchestration for the CV evaluation pipeline.

Defines the agents, tasks, and Crew assembly. The streamlined "recommendation
report" pipeline parses the CV and job, runs five parallel evaluators (HR,
hiring manager, technical, ATS, gap), consolidates the feedback, and renders
the final report. Optional steps: competitor simulation.
"""
from __future__ import annotations

import os
from pathlib import Path

from typing import Protocol

from crewai import Agent, Crew, Task, Process, LLM
from crewai.project import CrewBase, agent, crew, task

from src.constants import (
    DEFAULT_MODEL_HAIKU, DEFAULT_MODEL_SONNET,
    TASK_PARSE_JOB, TASK_PARSE_CV, TASK_HR_EVAL, TASK_HIRING_EVAL,
    TASK_TECHNICAL_EVAL, TASK_ATS_EVAL, TASK_GAP_ANALYSIS,
    TASK_SECOND_OPINION, TASK_COMPETITOR, TASK_CONSOLIDATE, TASK_INTERVIEW_PREP,
)
from src.settings import get_settings
from src.tools import (
    parse_job_pdf,
    parse_cv,
    compute_keyword_match,
    load_domain_knowledge_base,
)
from src.guardrails import (
    job_posting_completeness,
    candidate_profile_completeness,
    consolidated_feedback_present,
)
from src.models import (
    JobPosting,
    AgentEvaluation, GapAnalysis, ATSReport, SecondOpinion,
    CompetitorProfile,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

__all__ = ["CrewBuilder", "CrewPlugin", "CompetitorPlugin", "CVOptimizerCrew"]


class CrewBuilder(Protocol):
    """Minimal interface for objects that can produce a configured Crew."""

    def build(self) -> Crew: ...


class CrewPlugin(Protocol):
    """A composable extension to CVOptimizerCrew.

    Plugins contribute extra tasks appended to the base task list.
    Implement this protocol to add optional agents without modifying the crew.
    """

    def extra_tasks(self, crew_instance: "CVOptimizerCrew") -> list[Task]: ...


class CompetitorPlugin:
    """Optional competitor simulation — adds _competitor_simulation_task."""

    def extra_tasks(self, crew_instance: "CVOptimizerCrew") -> list[Task]:
        return [crew_instance._competitor_simulation_task()]


def _apply_role_config(base_config: dict, role_type_hint: str) -> dict:
    """Return a copy of `base_config` with role-type placeholders substituted.

    Keeps the mutation local to a helper so adding new role-specific
    substitutions doesn't require touching the agent method itself.
    """
    cfg = dict(base_config)
    cfg["role"] = cfg.get("role", "").replace("{role_type}", role_type_hint)
    return cfg


def _llm(model_kind: str = "sonnet", max_tokens: int | None = None) -> LLM:
    """Build an Anthropic LLM with `max_tokens` capped so a parallel evaluator
    burst stays under the standard plan's per-minute output budget (8k Sonnet).

    Sequential extraction tasks (CV/job parsing) can pass a higher `max_tokens`
    override — they run alone in phase 1, so they don't compete for the burst
    budget, and a full CandidateProfile JSON easily exceeds the 2k Haiku cap.

    A per-request `timeout` (override via `LLM_TIMEOUT_SECONDS`, default 300s)
    ensures a stalled completion or rate-limit backoff surfaces as an error
    instead of hanging the whole run indefinitely.
    """
    _s = get_settings()
    if model_kind == "haiku":
        model_id = _s.model_haiku
        default_tokens = 2048
    else:
        model_id = _s.model_sonnet
        default_tokens = 4096
    return LLM(
        model=f"anthropic/{model_id}",
        max_tokens=max_tokens or default_tokens,
        temperature=0.4,
        timeout=_s.llm_timeout_seconds,
    )


@CrewBase
class CVOptimizerCrew:
    agents_config = str(_PROJECT_ROOT / "config" / "agents.yaml")
    tasks_config = str(_PROJECT_ROOT / "config" / "tasks.yaml")

    def __init__(
        self,
        role_type_hint: str | None = None,
        plugins: list[CrewPlugin] | None = None,
    ) -> None:
        self.role_type_hint = role_type_hint or "Practitioner"
        self._plugins: list[CrewPlugin] = plugins or []

    # ─── AGENTS ────────────────────────────────────────────────────────────
    # Haiku for extraction/structuring (cheap, accurate); Sonnet for the
    # reasoning-heavy roles. Per-agent limits live in config/agents.yaml.

    # ── Haiku-tier agents (parsing & extraction) ─────────────────────────
    @agent
    def _job_posting_parser_agent(self) -> Agent:
        return Agent(config=self.agents_config["job_posting_parser_agent"],
                     tools=[parse_job_pdf], llm=_llm("haiku", max_tokens=8192),
                     verbose=True, max_iter=6, allow_delegation=False)

    @agent
    def _cv_parser_agent(self) -> Agent:
        return Agent(config=self.agents_config["cv_parser_agent"],
                     tools=[parse_cv], llm=_llm("haiku", max_tokens=8192),
                     verbose=True, max_iter=6, allow_delegation=False)

    @agent
    def _ats_optimizer_agent(self) -> Agent:
        return Agent(config=self.agents_config["ats_optimizer_agent"],
                     tools=[compute_keyword_match],
                     llm=_llm("haiku"),
                     verbose=True, max_iter=6, allow_delegation=False)

    # ── Sonnet-tier agents (reasoning-heavy) ─────────────────────────────
    @agent
    def _hr_specialist_agent(self) -> Agent:
        return Agent(config=self.agents_config["hr_specialist_agent"],
                     llm=_llm("sonnet"),
                     verbose=True, max_iter=8, allow_delegation=False)

    @agent
    def _hiring_manager_agent(self) -> Agent:
        return Agent(config=self.agents_config["hiring_manager_agent"],
                     llm=_llm("sonnet"),
                     verbose=True, max_iter=8, allow_delegation=False)

    @agent
    def _technical_specialist_agent(self) -> Agent:
        cfg = _apply_role_config(self.agents_config["technical_specialist_agent"], self.role_type_hint)
        kwargs: dict = dict(
            config=cfg,
            tools=[load_domain_knowledge_base],
            llm=_llm("sonnet"),
            verbose=True, max_iter=8, allow_delegation=False,
        )
        # Attach the curated knowledge base as a CrewAI Knowledge source so
        # the framework handles chunking + retrieval. Opt-in via CREW_MEMORY=1
        # to keep the zero-key install path working.
        if get_settings().crew_memory:
            from src.knowledge import embedder_config, knowledge_sources_for
            sources = knowledge_sources_for(self.role_type_hint)
            if sources:
                kwargs["knowledge_sources"] = sources
                kwargs["embedder"] = embedder_config()
        return Agent(**kwargs)

    @agent
    def _coordinator_agent(self) -> Agent:
        # No tools attached: every coordinator task in this pipeline (gap
        # analysis, second opinion, consolidation, interview prep) is pure
        # synthesis over upstream context. File-writing tools kept getting
        # invoked with empty args, so the .md / .docx outputs are generated
        # deterministically in main.py from the task outputs instead.
        return Agent(config=self.agents_config["coordinator_agent"],
                     tools=[],
                     llm=_llm("sonnet"),
                     verbose=True, max_iter=10,
                     allow_delegation=False)

    # ─── TASKS — ingestion ─────────────────────────────────────────────────

    @task
    def _parse_job_task(self) -> Task:
        return Task(
            config=self.tasks_config[TASK_PARSE_JOB],
            agent=self._job_posting_parser_agent(),
            output_pydantic=JobPosting,
            guardrail=job_posting_completeness,
            guardrail_max_retries=2,
        )

    @task
    def _parse_cv_task(self) -> Task:
        # output_pydantic intentionally omitted — CandidateProfile's nested
        # lists trigger Anthropic grammar-compilation timeouts.
        return Task(
            config=self.tasks_config[TASK_PARSE_CV],
            agent=self._cv_parser_agent(),
            guardrail=candidate_profile_completeness,
            guardrail_max_retries=2,
        )

    # ─── TASKS — parallel evaluation ───────────────────────────────────────

    @task
    def _hr_evaluation_task(self) -> Task:
        return Task(
            config=self.tasks_config[TASK_HR_EVAL],
            agent=self._hr_specialist_agent(),
            context=[self._parse_job_task(), self._parse_cv_task()],
            output_pydantic=AgentEvaluation,
            async_execution=True,
        )

    @task
    def _hiring_manager_evaluation_task(self) -> Task:
        return Task(
            config=self.tasks_config[TASK_HIRING_EVAL],
            agent=self._hiring_manager_agent(),
            context=[self._parse_job_task(), self._parse_cv_task()],
            output_pydantic=AgentEvaluation,
            async_execution=True,)

    @task
    def _technical_evaluation_task(self) -> Task:
        return Task(
            config=self.tasks_config[TASK_TECHNICAL_EVAL],
            agent=self._technical_specialist_agent(),
            context=[self._parse_job_task(), self._parse_cv_task()],
            output_pydantic=AgentEvaluation,
            async_execution=True,)

    @task
    def _ats_evaluation_task(self) -> Task:
        return Task(
            config=self.tasks_config[TASK_ATS_EVAL],
            agent=self._ats_optimizer_agent(),
            context=[self._parse_job_task(), self._parse_cv_task()],
            output_pydantic=ATSReport,
            async_execution=True,)

    @task
    def _gap_analysis_task(self) -> Task:
        return Task(
            config=self.tasks_config[TASK_GAP_ANALYSIS],
            agent=self._coordinator_agent(),
            context=[self._parse_job_task(), self._parse_cv_task()],
            output_pydantic=GapAnalysis,
            async_execution=True,)

    # ─── TASKS — tiebreaker ────────────────────────────────────────────────

    @task
    def _second_opinion_task(self) -> Task:
        return Task(
            config=self.tasks_config[TASK_SECOND_OPINION],
            agent=self._coordinator_agent(),
            context=[
                self._hr_evaluation_task(),
                self._hiring_manager_evaluation_task(),
                self._technical_evaluation_task(),
            ],
            output_pydantic=SecondOpinion,
        )

    # ─── TASKS — competitor simulation (optional) ──────────────────────────

    @task
    def _competitor_simulation_task(self) -> Task:
        return Task(
            config=self.tasks_config[TASK_COMPETITOR],
            agent=self._hiring_manager_agent(),
            context=[self._parse_job_task(), self._parse_cv_task()],
            output_pydantic=CompetitorProfile,
        )

    # ─── TASKS — synthesis ─────────────────────────────────────────────────

    @task
    def _consolidate_feedback_task(self) -> Task:
        ctx = [
            self._hr_evaluation_task(),
            self._hiring_manager_evaluation_task(),
            self._technical_evaluation_task(),
            self._ats_evaluation_task(),
            self._gap_analysis_task(),
            self._second_opinion_task(),
        ]
        # output_pydantic intentionally omitted — ConsolidatedFeedback's
        # List[PrioritizedChange] triggers grammar-compilation timeouts.
        return Task(
            config=self.tasks_config[TASK_CONSOLIDATE],
            agent=self._coordinator_agent(),
            context=ctx,
            guardrail=consolidated_feedback_present,
            guardrail_max_retries=2,
        )

    # ─── TASKS — insight generation ────────────────────────────────────────

    @task
    def _interview_prep_task(self) -> Task:
        return Task(
            config=self.tasks_config[TASK_INTERVIEW_PREP],
            agent=self._coordinator_agent(),
            context=[self._parse_job_task(), self._parse_cv_task(),
                     self._consolidate_feedback_task()],
        )

    # ─── Output assembly ───────────────────────────────────────────────────
    # There is intentionally NO render task: having the coordinator re-emit the
    # full JobReport JSON (copying the candidate profile + every evaluation
    # verbatim) was the single slowest call in the run and added nothing — the
    # host rebuilds the same report deterministically from each task's
    # structured output (see _augment_report_from_tasks in main.py).

    # ─── CREW ──────────────────────────────────────────────────────────────

    @crew
    def crew(self) -> Crew:
        all_tasks = [
            # Ingestion
            self._parse_job_task(),
            self._parse_cv_task(),
            # Parallel evaluation
            self._hr_evaluation_task(),
            self._hiring_manager_evaluation_task(),
            self._technical_evaluation_task(),
            self._ats_evaluation_task(),
            self._gap_analysis_task(),
            # Synthesis
            self._second_opinion_task(),
            self._consolidate_feedback_task(),
        ]
        for plugin in self._plugins:
            all_tasks.extend(plugin.extra_tasks(self))

        all_tasks.append(self._interview_prep_task())

        # CrewAI memory is opt-in to keep the zero-key install path working.
        # Enable with CREW_MEMORY=1; override embedder with CREW_EMBEDDER_PROVIDER.
        memory_enabled = get_settings().crew_memory
        crew_kwargs: dict = {
            "agents": self.agents,
            "tasks": all_tasks,
            "process": Process.sequential,
            "verbose": True,
            "memory": memory_enabled,
            "cache": True,
        }
        if memory_enabled:
            from src.knowledge import embedder_config
            crew_kwargs["embedder"] = embedder_config()
        return Crew(**crew_kwargs)

    def build(self) -> Crew:
        """Satisfy CrewBuilder protocol — delegates to crew()."""
        return self.crew()
