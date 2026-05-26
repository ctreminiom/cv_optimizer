"""CLI presentation helpers built on Rich (with stdlib `print` fallback).

Use these for user-facing CLI output. For diagnostic logging (tool calls,
retries, cache hits) use `src.logging_config.get_logger` instead.
"""
from __future__ import annotations

import sys
from typing import Any

__all__ = ["HAS_RICH", "console", "Panel", "Table", "info", "ok", "warn", "err", "banner"]

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    HAS_RICH = True
    console: Any = Console()
except ImportError:
    HAS_RICH = False
    console = None
    Panel = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]


def info(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold cyan]ℹ[/bold cyan] {msg}")
    else:
        print(f"ℹ {msg}")


def ok(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold green]✓[/bold green] {msg}")
    else:
        print(f"✓ {msg}")


def warn(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold yellow]⚠[/bold yellow] {msg}")
    else:
        print(f"⚠ {msg}")


def err(msg: str) -> None:
    if HAS_RICH:
        console.print(f"[bold red]✗[/bold red] {msg}")
    else:
        print(f"✗ {msg}", file=sys.stderr)


def banner(title: str) -> None:
    if HAS_RICH:
        console.print(Panel(f"[bold]{title}[/bold]", border_style="cyan"))
    else:
        print(f"\n{'═' * 60}\n  {title}\n{'═' * 60}")
