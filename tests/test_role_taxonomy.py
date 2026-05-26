"""Unit tests for role_taxonomy loader (C7)."""

from __future__ import annotations

from src.role_taxonomy import all_aliases, expand_keywords


def test_expand_keywords_maps_canonical_to_synonyms():
    out = expand_keywords(["product_manager"])
    assert "product_manager" in out
    syns = [s.lower() for s in out["product_manager"]]
    assert "pm" in syns
    assert "senior product manager" in syns


def test_expand_keywords_handles_alias_input():
    """When user passes 'PM', taxonomy should resolve to product_manager synonyms."""
    out = expand_keywords(["PM"])
    assert "PM" in out
    syns = [s.lower() for s in out["PM"]]
    assert "product_manager" in syns or "product manager" in syns


def test_expand_keywords_skips_unknown_keywords():
    out = expand_keywords(["totally_made_up_role_xyz"])
    assert out == {}


def test_all_aliases_includes_canonical_and_synonyms():
    aliases = all_aliases()
    assert "pm" in aliases
    assert aliases["pm"] == "product_manager"
    assert aliases["sre"] == "devops_engineer"
