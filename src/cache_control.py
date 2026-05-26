"""
cache_control.py — Recommendation #2.

Helpers for Anthropic prompt caching. CrewAI's LLM wrapper does not
expose cache_control directly, so this module provides utilities for
agents that need to make caching-aware calls via the native Anthropic
SDK (used by tools that call the API directly, e.g. context windowing).

Caching strategy:
  • Agent personas + system prompts → cache (1 hour TTL)
  • CandidateProfile (read by 7+ tasks) → cache (5 min TTL)
  • JobPosting (read by 5+ tasks) → cache (5 min TTL)

Usage:
    from src.cache_control import build_cached_messages
    messages = build_cached_messages(system_prompt, stable_context, user_msg)

The Anthropic SDK then sees ephemeral cache markers and reuses cached
prefixes — input tokens billed at 0.1× standard rate after the first call.
"""
from __future__ import annotations

import os
from typing import Any


def build_cached_messages(
    system_prompt: str,
    stable_context: str,
    user_message: str,
    cache_system: bool = True,
    cache_context: bool = True,
) -> list[dict[str, Any]]:
    """
    Build an Anthropic messages array with cache_control markers on the
    system prompt and stable context. The dynamic user message at the end
    is NOT cached.
    """
    messages: list[dict[str, Any]] = []

    if system_prompt:
        sys_block: dict[str, Any] = {"type": "text", "text": system_prompt}
        if cache_system:
            sys_block["cache_control"] = {"type": "ephemeral"}
        messages.append({"role": "user", "content": [sys_block]})
        messages.append({"role": "assistant", "content": "Understood."})

    ctx_block: dict[str, Any] = {"type": "text", "text": stable_context}
    if cache_context:
        ctx_block["cache_control"] = {"type": "ephemeral"}

    messages.append({
        "role": "user",
        "content": [
            ctx_block,
            {"type": "text", "text": user_message},
        ],
    })
    return messages


def call_with_cache(
    system_prompt: str,
    stable_context: str,
    user_message: str,
    model: str | None = None,
    max_tokens: int = 4096,
) -> str:
    """
    Direct Anthropic call with prompt caching. Used by tools that bypass
    the CrewAI LLM wrapper (e.g. the context-windowing pre-filter).
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic SDK not installed: pip install anthropic")

    client = Anthropic()
    model = model or os.getenv("MODEL_HAIKU", "claude-haiku-4-5-20251001")

    messages = build_cached_messages(
        system_prompt="",
        stable_context=stable_context,
        user_message=user_message,
    )

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }] if system_prompt else None,
        messages=messages,
    )

    # Concatenate text blocks
    parts: List[str] = []
    for block in resp.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)
