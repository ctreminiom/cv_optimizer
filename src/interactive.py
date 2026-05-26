"""
interactive.py — Recommendation #12.

Implements the interactive review mode flag (`--mode interactive`).
After the CV Rewriter produces each bullet, pause and let the user
keep / edit / revert / skip it.

User decisions are persisted via memory.py so they inform future runs
of the same candidate.
"""

from __future__ import annotations

from src.memory import recall, remember
from src.models import RewrittenBullet


def review_bullet(bullet: RewrittenBullet, candidate_name: str = "default") -> RewrittenBullet:
    """
    Show original vs rewritten and prompt the user.
    Returns the (possibly modified) RewrittenBullet.
    """
    print()
    print("─" * 70)
    print(f"  ORIGINAL : {bullet.original}")
    print(f"  ADAPTED  : {bullet.rewritten}")
    if bullet.reasoning:
        print(f"  WHY      : {bullet.reasoning}")
    print("─" * 70)
    print("  [k]eep  [e]dit  [r]evert (use original)  [s]kip (drop entirely)")

    choice = input("  > ").strip().lower()

    if choice in ("e", "edit"):
        print("  Enter your version (one line):")
        edited = input("  > ").strip()
        if edited:
            bullet = bullet.model_copy(
                update={
                    "rewritten": edited,
                    "reasoning": "user edit during interactive review",
                }
            )
            _record_decision(
                candidate_name, "user_edit", {"original": bullet.original, "kept": edited}
            )
    elif choice in ("r", "revert"):
        bullet = bullet.model_copy(
            update={
                "rewritten": bullet.original,
                "reasoning": "user reverted to original",
            }
        )
        _record_decision(candidate_name, "user_revert", {"text": bullet.original})
    elif choice in ("s", "skip"):
        bullet = bullet.model_copy(
            update={
                "rewritten": "",
                "reasoning": "user skipped",
            }
        )
    else:
        # default → keep
        _record_decision(
            candidate_name,
            "user_keep",
            {"original": bullet.original, "rewritten": bullet.rewritten},
        )

    return bullet


def review_section(
    section_name: str, bullets: list[RewrittenBullet], candidate_name: str = "default"
) -> list[RewrittenBullet]:
    """Walk the user through every bullet in a section."""
    print(f"\n══ Reviewing section: {section_name} ══")
    return [review_bullet(b, candidate_name) for b in bullets]


def get_user_preferences(candidate_name: str = "default") -> dict:
    """Pull learned preferences from previous interactive sessions."""
    return {
        "edits": recall(f"interactive:{candidate_name}", "user_edit") or [],
        "reverts": recall(f"interactive:{candidate_name}", "user_revert") or [],
        "approvals": recall(f"interactive:{candidate_name}", "user_keep") or [],
    }


def _record_decision(candidate_name: str, kind: str, payload: dict) -> None:
    """Persist user decisions so future runs learn the candidate's voice."""
    namespace = f"interactive:{candidate_name}"
    history = recall(namespace, kind) or []
    if not isinstance(history, list):
        history = []
    history.append(payload)
    # cap to 100 entries
    history = history[-100:]
    remember(namespace, kind, history)
