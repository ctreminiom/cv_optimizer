"""Smoke tests for the presentation layer (B11 extraction)."""
from __future__ import annotations

import importlib

from src import presentation


def test_helpers_run_without_raising(capsys):
    presentation.info("hello")
    presentation.ok("done")
    presentation.warn("careful")
    presentation.err("broken")
    presentation.banner("Section")
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "hello" in combined
    assert "done" in combined
    assert "careful" in combined
    assert "broken" in combined
    assert "Section" in combined


def test_main_legacy_aliases_are_callable():
    """main.py imports the minimal presentation helpers it uses directly."""
    main = importlib.import_module("main")
    assert callable(main._info)
    assert callable(main._err)
