"""LLM client abstraction for non-CrewAI call sites.

All functions that make direct Anthropic API calls (not via CrewAI agents)
depend on LLMClientProtocol and receive a client via injection.  Use
get_default_client() as the production default; pass a mock in tests.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["LLMClientProtocol", "get_default_client"]


@runtime_checkable
class LLMClientProtocol(Protocol):
    """Minimal interface for single-turn, blocking LLM completions."""

    def complete(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
    ) -> str:
        """Return the text of the first content block. Raise on error."""
        ...


class _AnthropicClient:
    """Production implementation backed by anthropic.Anthropic."""

    def __init__(self, api_key: str) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
    ) -> str:
        resp = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        return resp.content[0].text if resp.content else ""


def get_default_client() -> LLMClientProtocol:
    """Return a production client configured from Settings.

    Raises ImportError  if the `anthropic` package is not installed.
    Raises ValidationError if ANTHROPIC_API_KEY is missing from the environment.
    """
    from src.settings import get_settings

    settings = get_settings()
    api_key = settings.reveal(settings.anthropic_api_key) or ""
    return _AnthropicClient(api_key=api_key)
