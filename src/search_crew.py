"""
search_crew.py — Job search subcommand.

A focused 2-agent crew that takes a candidate profile (parsed from the
master CV or supplied directly) and returns a list of JobOpportunity
items with absolute URLs.

  1. Profile Reader        → CandidateProfile + role keywords
  2. Job Researcher        → searches public boards, scores results

The Job Researcher uses the search_jobs tool (which prefers Tavily/Serper
when configured, and always includes deep-link fallbacks to LinkedIn,
Indeed CR, Computrabajo, Hireline, Tecoloco, Encuentra24, Google Jobs).
"""

from __future__ import annotations

import os
from pathlib import Path

from crewai import LLM, Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from src.constants import DEFAULT_MODEL_HAIKU, DEFAULT_MODEL_SONNET, TASK_PARSE_CV
from src.tools import parse_cv, search_jobs

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _llm(kind: str = "haiku") -> LLM:
    if kind == "haiku":
        return LLM(model=f"anthropic/{os.getenv('MODEL_HAIKU', DEFAULT_MODEL_HAIKU)}")
    return LLM(model=f"anthropic/{os.getenv('MODEL_SONNET', DEFAULT_MODEL_SONNET)}")


@CrewBase
class JobSearchCrew:
    agents_config = str(_PROJECT_ROOT / "config" / "agents.yaml")
    tasks_config = str(_PROJECT_ROOT / "config" / "tasks.yaml")

    def __init__(
        self,
        location: str = "Costa Rica",
        max_results: int = 20,
        modality: str | None = None,
        seniority: str | None = None,
        role: str | None = None,
        keywords: list[str] | None = None,
        contract_type: str | None = None,
        include_sources: list[str] | None = None,
        min_match: int = 0,
    ) -> None:
        self.location = location
        self.max_results = max_results
        self.modality = modality
        self.seniority = seniority
        self.role = role
        self.keywords = keywords or []
        self.contract_type = contract_type
        self.include_sources = include_sources
        self.min_match = min_match

    # ─── AGENTS ────────────────────────────────────────────────────────────

    @agent
    def cv_parser_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["cv_parser_agent"],
            tools=[parse_cv],
            llm=_llm("haiku"),
            verbose=True,
        )

    @agent
    def job_researcher_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["job_researcher_agent"],
            tools=[search_jobs],
            llm=_llm("sonnet"),
            verbose=True,
        )

    # ─── TASKS ─────────────────────────────────────────────────────────────

    @task
    def parse_cv_task(self) -> Task:
        # output_pydantic removed — CandidateProfile nested lists cause grammar timeouts
        return Task(
            config=self.tasks_config[TASK_PARSE_CV],
            agent=self.cv_parser_agent(),
        )

    @task
    def search_jobs_task(self) -> Task:
        # output_pydantic removed — JobSearchResult contains List[JobOpportunity]
        return Task(
            config=self.tasks_config["search_jobs_task"],
            agent=self.job_researcher_agent(),
            context=[self.parse_cv_task()],
            output_file="output/job_search_results.json",
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=[self.parse_cv_task(), self.search_jobs_task()],
            process=Process.sequential,
            verbose=True,
        )
