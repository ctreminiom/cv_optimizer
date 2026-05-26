"""Agent interaction tracker and workflow visualization for the run command.

Extracted from main.py (SRP Phase 3a). No logic changes.
"""

from __future__ import annotations

import time
from typing import Any

from src.constants import (
    TASK_ATS_EVAL,
    TASK_COMPETITOR,
    TASK_CONSOLIDATE,
    TASK_COVER_LETTER,
    TASK_EXTRACT_VOICE,
    TASK_GAP_ANALYSIS,
    TASK_HIRING_EVAL,
    TASK_HR_EVAL,
    TASK_HUMANIZE_CV,
    TASK_HUMANIZE_RETRY,
    TASK_INTERVIEW_PREP,
    TASK_MIRRORING_CHECK,
    TASK_PARSE_CV,
    TASK_PARSE_JOB,
    TASK_REWRITE_CV,
    TASK_SECOND_OPINION,
    TASK_TECHNICAL_EVAL,
    TASK_VERIFICATION,
)
from src.presentation import (
    HAS_RICH as _HAS_RICH,
)
from src.presentation import (
    Panel,
    Table,
)
from src.presentation import (
    console as _console,
)

AGENT_WORKFLOW_PHASES = [
    {
        "name": "Phase 1 — Ingestion",
        "color": "cyan",
        "icon": "📥",
        "agents": [
            ("Job Posting Parser", "Extracts structured JobPosting from the posting"),
            ("CV Parser", "Extracts CandidateProfile from your CV"),
        ],
    },
    {
        "name": "Phase 2 — Multi-Agent Evaluation (parallel)",
        "color": "yellow",
        "icon": "⚖️",
        "agents": [
            ("HR Specialist", "Scores cultural & soft-skill fit"),
            ("Hiring Manager", "Scores impact, leadership, decision-making"),
            ("Technical Specialist", "Scores domain expertise & tech alignment"),
            ("ATS Optimizer", "Computes keyword match & format issues"),
            ("Coordinator (Gap)", "Identifies critical gaps & framing chances"),
        ],
    },
    {
        "name": "Phase 3 — Synthesis",
        "color": "magenta",
        "icon": "🧩",
        "agents": [
            ("Coordinator (2nd-Op)", "Tiebreaker when scores diverge"),
            ("Coordinator (Consol.)", "Merges all evals into prioritized changes"),
        ],
    },
    {
        "name": "Phase 4 — Insight Generation",
        "color": "green",
        "icon": "💡",
        "agents": [
            ("Coordinator (Prep)", "Generates likely interview questions"),
        ],
    },
    # Output assembly is deterministic (host-side, no LLM) — see
    # _augment_report_from_tasks — so it is not shown as an agent phase.
]


# Map of task_name → emoji + colour for at-a-glance UX cues.
TASK_VIS = {
    TASK_PARSE_JOB: ("📥", "cyan", "Parsing job posting"),
    TASK_PARSE_CV: ("📥", "cyan", "Parsing CV"),
    TASK_EXTRACT_VOICE: ("🎙️", "cyan", "Extracting voice signature"),
    TASK_HR_EVAL: ("👥", "yellow", "HR specialist evaluating"),
    TASK_HIRING_EVAL: ("🎯", "yellow", "Hiring manager evaluating"),
    TASK_TECHNICAL_EVAL: ("🛠️", "yellow", "Technical specialist evaluating"),
    TASK_ATS_EVAL: ("🤖", "yellow", "ATS keyword analysis"),
    TASK_GAP_ANALYSIS: ("🔍", "yellow", "Gap analysis"),
    TASK_SECOND_OPINION: ("⚖️", "magenta", "Second opinion (tiebreaker)"),
    TASK_COMPETITOR: ("🥊", "magenta", "Competitor simulation"),
    TASK_CONSOLIDATE: ("🧩", "magenta", "Consolidating feedback"),
    TASK_REWRITE_CV: ("✍️", "green", "Rewriting CV bullets"),
    TASK_HUMANIZE_CV: ("💬", "green", "Humanizing language"),
    TASK_HUMANIZE_RETRY: ("🔁", "green", "Humanize retry"),
    TASK_MIRRORING_CHECK: ("🪞", "green", "Checking JD mirroring"),
    TASK_VERIFICATION: ("✅", "green", "Verifying facts"),
    TASK_INTERVIEW_PREP: ("🎤", "green", "Generating interview Qs"),
    TASK_COVER_LETTER: ("📝", "green", "Drafting cover letter"),
}


def print_agent_workflow_graph(skip_cover_letter: bool, with_competitor: bool) -> None:
    """Pre-run banner that visualizes the multi-agent collaboration graph."""
    if _HAS_RICH:
        from rich.tree import Tree

        tree = Tree(
            "[bold white]🎯 Multi-Agent CV Optimization Crew[/bold white]"
            "  [dim](data flows top→bottom; phase 2 runs in parallel)[/dim]",
            guide_style="dim",
        )
        for phase in AGENT_WORKFLOW_PHASES:
            color = phase["color"]
            phase_node = tree.add(f"[bold {color}]{phase['icon']} {phase['name']}[/bold {color}]")
            for agent_name, role in phase["agents"]:
                if agent_name == "CV Rewriter (Cover)" and skip_cover_letter:
                    continue
                phase_node.add(
                    f"[bold {color}]●[/bold {color}] [white]{agent_name:<22}[/white]"
                    f"  [dim italic]{role}[/dim italic]"
                )
            if phase["name"].startswith("Phase 2") and with_competitor:
                phase_node.add(
                    f"[bold {color}]●[/bold {color}] [white]Competitor Sim       [/white]"
                    f"  [dim italic]Hypothetical strong candidate analysis[/dim italic]"
                )
        _console.print(
            Panel(tree, title="[bold]Agent Workflow[/bold]", border_style="cyan", padding=(1, 2))
        )
    else:
        print("\n┌─ Multi-Agent CV Optimization Crew ─────────────────────────")
        for phase in AGENT_WORKFLOW_PHASES:
            print(f"│ {phase['icon']} {phase['name']}")
            for agent_name, role in phase["agents"]:
                if agent_name == "CV Rewriter (Cover)" and skip_cover_letter:
                    continue
                print(f"│    • {agent_name:<22}  {role}")
        print("└────────────────────────────────────────────────────────────\n")


class AgentInteractionTracker:
    """Hooks into CrewAI's task lifecycle (via task_callback) to track per-task
    timing, render a live progress bar, and emit a final summary table.

    UX:
      • Pre-kickoff: announces total task count
      • Per task complete: prints a coloured line with a unicode progress bar
        showing how far through the pipeline we are
      • Post-kickoff: a Rich table with each agent's timing and output type
    """

    def __init__(self, total_tasks: int = 0) -> None:
        self.events: list[dict] = []
        self.total_tasks = max(total_tasks, 0)
        self._kickoff_started = time.time()
        self._last_event_at = time.time()

    def announce_start(self) -> None:
        """One-line banner above the live progress feed."""
        if _HAS_RICH:
            _console.print(
                f"\n[bold cyan]🚀 Crew kickoff[/bold cyan]  "
                f"[dim]· {self.total_tasks} task(s) queued · live progress below[/dim]\n"
            )
        else:
            print(f"\n>> Crew kickoff — {self.total_tasks} tasks queued <<\n")

    def _progress_bar(self, completed: int, total: int, width: int = 24) -> tuple[str, int]:
        if total <= 0:
            return ("░" * width, 0)
        pct = min(100, int(round(100 * completed / total)))
        filled = int(round(width * completed / total))
        return ("█" * filled + "░" * (width - filled), pct)

    def on_task_complete(self, task_output: Any) -> None:
        """Called by CrewAI after each task finishes — prints a progress line."""
        try:
            task_name = (
                getattr(task_output, "name", "") or getattr(task_output, "task_name", "") or ""
            )
            agent_role = getattr(task_output, "agent", "") or ""
            if getattr(task_output, "pydantic", None) is not None:
                kind = type(task_output.pydantic).__name__
            else:
                kind = "text"
            now = time.time()
            elapsed = round(now - self._last_event_at, 1)
            self._last_event_at = now
            self.events.append(
                {
                    "task_name": task_name,
                    "agent_role": agent_role,
                    "kind": kind,
                    "elapsed": elapsed,
                }
            )
        except Exception:
            return

        completed = len(self.events)
        total = self.total_tasks or completed
        bar, pct = self._progress_bar(completed, total)

        emoji, colour, action = TASK_VIS.get(task_name, ("•", "white", task_name or "task"))
        if _HAS_RICH:
            _console.print(
                f"[bold {colour}]{emoji}[/bold {colour}]  "
                f"[bold green]{bar}[/bold green] [bold]{pct:>3}%[/bold]  "
                f"[dim]({completed}/{total})[/dim]  "
                f"[{colour}]{action}[/{colour}]  "
                f"[dim italic]→ {kind} · {elapsed}s[/dim italic]"
            )
        else:
            print(f"  {emoji} [{bar}] {pct}% ({completed}/{total}) {action} → {kind} ({elapsed}s)")

    def render_workflow_with_timings(
        self, skip_cover_letter: bool = False, with_competitor: bool = False
    ) -> None:
        """Re-render the workflow tree with actual per-task execution times."""
        label_to_task = {
            "Job Posting Parser": TASK_PARSE_JOB,
            "CV Parser": TASK_PARSE_CV,
            "Voice Extractor": TASK_EXTRACT_VOICE,
            "HR Specialist": TASK_HR_EVAL,
            "Hiring Manager": TASK_HIRING_EVAL,
            "Technical Specialist": TASK_TECHNICAL_EVAL,
            "ATS Optimizer": TASK_ATS_EVAL,
            "Coordinator (Gap)": TASK_GAP_ANALYSIS,
            "Coordinator (2nd-Op)": TASK_SECOND_OPINION,
            "Coordinator (Consol.)": TASK_CONSOLIDATE,
            "CV Rewriter": TASK_REWRITE_CV,
            "Authenticity Agent": TASK_HUMANIZE_CV,
            "Coordinator (Mirror)": TASK_MIRRORING_CHECK,
            "Verification Agent": TASK_VERIFICATION,
            "Coordinator (Prep)": TASK_INTERVIEW_PREP,
            "CV Rewriter (Cover)": TASK_COVER_LETTER,
            "Competitor Sim": TASK_COMPETITOR,
        }
        elapsed_by_task: dict[str, float] = {}
        for ev in self.events:
            t = ev.get("task_name") or ""
            if t and t not in elapsed_by_task:
                elapsed_by_task[t] = ev.get("elapsed", 0) or 0
            elif t == TASK_HUMANIZE_RETRY and TASK_HUMANIZE_CV in elapsed_by_task:
                elapsed_by_task["humanize_cv_task"] += ev.get("elapsed", 0) or 0

        total = round(time.time() - self._kickoff_started, 1)

        if _HAS_RICH:
            from rich.tree import Tree

            tree = Tree(
                f"[bold white]🎯 Multi-Agent CV Optimization Crew[/bold white]  "
                f"[dim](total wall-clock: [bold green]{total}s[/bold green])[/dim]",
                guide_style="dim",
            )
            for phase in AGENT_WORKFLOW_PHASES:
                color = phase["color"]
                phase_node = tree.add(
                    f"[bold {color}]{phase['icon']} {phase['name']}[/bold {color}]"
                )
                for agent_name, role in phase["agents"]:
                    if agent_name == "CV Rewriter (Cover)" and skip_cover_letter:
                        continue
                    task_name = label_to_task.get(agent_name)
                    elapsed = elapsed_by_task.get(task_name, 0) if task_name else 0
                    if elapsed:
                        time_str = f"[bold green]{elapsed}s[/bold green]"
                        marker = f"[bold {color}]●[/bold {color}]"
                    else:
                        time_str = "[dim]— skipped[/dim]"
                        marker = "[dim]○[/dim]"
                    phase_node.add(
                        f"{marker} [white]{agent_name:<22}[/white]  "
                        f"{time_str}  "
                        f"[dim italic]{role}[/dim italic]"
                    )
                if phase["name"].startswith("Phase 2") and with_competitor:
                    elapsed = elapsed_by_task.get("competitor_simulation_task", 0)
                    time_str = (
                        f"[bold green]{elapsed}s[/bold green]"
                        if elapsed
                        else "[dim]— skipped[/dim]"
                    )
                    phase_node.add(
                        f"[bold {color}]●[/bold {color}] [white]Competitor Sim       [/white]"
                        f"  {time_str}  "
                        f"[dim italic]Hypothetical strong candidate analysis[/dim italic]"
                    )
            _console.print(
                Panel(
                    tree,
                    title="[bold]Agent Workflow — Execution Recap[/bold]",
                    border_style="green",
                    padding=(1, 2),
                )
            )
        else:
            print("\n=== Multi-Agent CV Optimization Crew — Execution Recap ===")
            for phase in AGENT_WORKFLOW_PHASES:
                print(f"\n  {phase['icon']} {phase['name']}")
                for agent_name, role in phase["agents"]:
                    if agent_name == "CV Rewriter (Cover)" and skip_cover_letter:
                        continue
                    task_name = label_to_task.get(agent_name)
                    elapsed = elapsed_by_task.get(task_name, 0) if task_name else 0
                    suffix = f"{elapsed}s" if elapsed else "skipped"
                    print(f"    • {agent_name:<22}  {suffix:>10}  {role}")
            print(f"\n  Total wall-clock: {total}s")

    def render_summary(self) -> None:
        """Print a Rich table summarising every task after the crew finishes."""
        if not self.events:
            return
        total_time = round(time.time() - self._kickoff_started, 1)
        if _HAS_RICH:
            t = Table(
                title="🤖 Agent Execution Summary",
                show_header=True,
                header_style="bold cyan",
                border_style="dim",
            )
            t.add_column("#", style="dim", width=3, justify="right")
            t.add_column("Phase", style="white", width=4)
            t.add_column("Task", style="white")
            t.add_column("Agent", style="cyan")
            t.add_column("Output", style="yellow")
            t.add_column("Elapsed", style="green", justify="right")
            for i, ev in enumerate(self.events, 1):
                emoji, _, _ = TASK_VIS.get(ev["task_name"], ("•", "white", ""))
                t.add_row(
                    str(i),
                    emoji,
                    (ev["task_name"] or "—")[:32],
                    (ev["agent_role"] or "—")[:24],
                    ev["kind"],
                    f"{ev['elapsed']}s" if ev["elapsed"] else "—",
                )
            _console.print(t)
            sum_per_task = sum(ev.get("elapsed", 0) or 0 for ev in self.events)
            _console.print(
                f"[dim]Wall-clock:[/dim] "
                f"[bold green]{total_time}s[/bold green] · "
                f"[dim]Sum of per-task time:[/dim] "
                f"[green]{round(sum_per_task, 1)}s[/green] · "
                f"[dim]Tasks completed:[/dim] "
                f"[bold]{len(self.events)}/{self.total_tasks or len(self.events)}[/bold]"
            )
        else:
            print("\n=== Agent Execution Summary ===")
            for i, ev in enumerate(self.events, 1):
                print(
                    f"  {i}. {ev['task_name']:<32} {ev['agent_role']:<24} "
                    f"{ev['kind']:<20} {ev['elapsed']}s"
                )
            print(f"Total wall-clock: {total_time}s")
