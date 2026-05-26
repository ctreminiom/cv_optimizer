"""Compatibility tests: guardrail functions must pass CrewAI's Task validator.

CrewAI's Task.validate_guardrail_function uses inspect.signature() — NOT
typing.get_type_hints() — to inspect the return annotation.  This matters
because:

  • With `from __future__ import annotations` in guardrails.py, every
    annotation becomes a lazy string at definition time.  inspect.signature()
    returns that string (e.g. "Result"), so get_origin("Result") → None and
    the validator raises:
        "If return type is annotated, it must be Tuple[bool, Any]"

  • With native `tuple[bool, Any]` (lowercase) instead of typing.Tuple, the
    origin check still passes (get_origin(tuple[bool, Any]) is tuple), but
    this test exists so we notice immediately if that assumption ever breaks
    across CrewAI versions.

The unit tests in test_guardrails.py call guardrail functions directly and
will pass even when both problems are present.  These tests catch the gap.
"""

from __future__ import annotations

import inspect
from typing import Any, get_args, get_origin

import pytest
from crewai import Task

from src.guardrails import (
    adapted_cv_no_fabrication,
    candidate_profile_completeness,
    consolidated_feedback_present,
    job_posting_completeness,
    mirroring_under_threshold,
)

_ALL_GUARDRAILS = [
    job_posting_completeness,
    candidate_profile_completeness,
    consolidated_feedback_present,
    adapted_cv_no_fabrication,
    mirroring_under_threshold,
]


@pytest.mark.parametrize("fn", _ALL_GUARDRAILS, ids=lambda f: f.__name__)
class TestGuardrailCrewAICompat:
    """Each test mirrors one step of Task.validate_guardrail_function so that
    a failure points directly at the broken constraint."""

    def test_annotation_is_not_a_string(self, fn):
        """Return annotation must be a type object, not a string.

        `from __future__ import annotations` makes inspect.signature() return
        the raw string instead of the resolved type, causing get_origin() to
        return None and the Task validator to reject the guardrail.
        """
        ann = inspect.signature(fn).return_annotation
        assert ann is not inspect.Parameter.empty, (
            f"{fn.__name__} has no return annotation — add '-> Tuple[bool, Any]'"
        )
        assert not isinstance(ann, str), (
            f"{fn.__name__} return annotation is the string {ann!r} instead of a "
            "type object.  Most likely cause: 'from __future__ import annotations' "
            "is present in guardrails.py — remove it so CrewAI's Task validator "
            "receives a real type."
        )

    def test_annotation_origin_is_tuple(self, fn):
        """get_origin(annotation) must be the built-in tuple.

        CrewAI checks: get_origin(return_annotation) is tuple
        This fails for bare string annotations and for non-tuple types.
        """
        ann = inspect.signature(fn).return_annotation
        origin = get_origin(ann)
        assert origin is tuple, (
            f"{fn.__name__} annotation origin is {origin!r}; expected tuple.  "
            "Annotate the return type as Tuple[bool, Any] (from typing)."
        )

    def test_annotation_args_match_bool_any(self, fn):
        """Annotation args must be exactly (bool, Any).

        CrewAI checks:
            len(args) == 2 and args[0] is bool and args[1] is Any (or str/TaskOutput)
        """
        ann = inspect.signature(fn).return_annotation
        args = get_args(ann)
        assert len(args) == 2, f"{fn.__name__} annotation has {len(args)} type arg(s); expected 2"
        assert args[0] is bool, f"{fn.__name__} annotation arg[0] is {args[0]!r}; expected bool"
        assert args[1] is Any, f"{fn.__name__} annotation arg[1] is {args[1]!r}; expected Any"

    def test_crewai_task_validator_accepts_guardrail(self, fn):
        """The actual CrewAI validator must not raise.

        This is the highest-fidelity check: it calls Task.validate_guardrail_function
        directly, so any future change to CrewAI's validation logic is caught here
        even if the lower-level annotation checks above still pass.
        """
        try:
            Task.validate_guardrail_function(fn)
        except Exception as exc:
            pytest.fail(
                f"Task.validate_guardrail_function({fn.__name__!r}) raised:\n"
                f"  {exc}\n"
                "The guardrail will be rejected at Task construction time in "
                "production even though unit tests that call it directly pass."
            )
