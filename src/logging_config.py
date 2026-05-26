"""Structured logging configuration.

Human-readable in a TTY (Rich-style), JSON when stdout is not a TTY (CI / logs).
Tools and crew internals should `logger = structlog.get_logger(__name__)`.
The CLI presentation layer keeps using `_info/_ok/_warn/_err` in main.py.
"""

from __future__ import annotations

import logging
import os
import sys

try:
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:  # graceful fallback for first-time installs
    _HAS_STRUCTLOG = False


def configure_logging(level: str | None = None) -> None:
    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        stream=sys.stderr,
    )

    if not _HAS_STRUCTLOG:
        return

    is_tty = sys.stderr.isatty()
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.dev.ConsoleRenderer(colors=is_tty)
        if is_tty
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)
    return logging.getLogger(name)
