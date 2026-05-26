"""Voice signature extraction tool.

Analyses a candidate's writing style: formality, bullet starters,
quantification style, and representative example bullets.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from crewai.tools import tool

__all__ = ["extract_voice_signature"]


@tool("extract_voice_signature")
def extract_voice_signature(text_json: str) -> str:
    """
    Analyzes the candidate's master CV to capture authentic style:
    formality, bullet starters, average bullet length, signature phrases,
    and the 5 most representative bullets (used as few-shot exemplars by
    the Authenticity Agent — recommendation #4).
    """
    try:
        data = json.loads(text_json)
        text = data.get("text", "")
    except Exception as e:
        return json.dumps({"error": f"invalid input: {e}"})

    bullets = [ln.strip().lstrip("•-*").strip()
               for ln in text.splitlines()
               if ln.strip().startswith(("•", "-", "*"))]
    bullets = [b for b in bullets if b]

    starters = [b.split()[0] for b in bullets if b.split()]
    avg_words = (sum(len(b.split()) for b in bullets) / len(bullets)) if bullets else 0

    text_lower = text.lower()
    contractions = sum(1 for c in ["i'm", "i've", "i'd", "don't", "can't", "won't"]
                       if c in text_lower)
    formal_markers = sum(1 for f in ["furthermore", "moreover", "additionally", "consequently"]
                         if f in text_lower)
    formality = ("casual" if contractions > formal_markers
                 else "formal" if formal_markers > contractions + 2
                 else "balanced")

    metric_count = len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|x|k|m|b|hours?|days?|weeks?|months?|years?)",
                                  text_lower))
    bullet_count = max(len(bullets), 1)
    metric_ratio = metric_count / bullet_count
    qstyle = ("heavy_metrics" if metric_ratio > 0.6
              else "selective" if metric_ratio > 0.2
              else "qualitative")

    # #4 — pick the 5 most representative bullets:
    #      prefer bullets with quantified impact + median length.
    target_len = max(int(avg_words), 10)
    def _score(b: str) -> float:
        n = len(b.split())
        len_score = 1.0 / (1 + abs(n - target_len) / max(target_len, 1))
        has_metric = bool(re.search(r"\d+(?:\.\d+)?\s*(?:%|x|k|m|b)", b.lower()))
        return len_score + (0.5 if has_metric else 0)

    representative = sorted(bullets, key=_score, reverse=True)[:6]

    return json.dumps({
        "formality_level": formality,
        "typical_bullet_starters": [s for s, _ in Counter(starters).most_common(8)],
        "avg_bullet_word_count": int(avg_words),
        "signature_phrases": [],
        "quantification_style": qstyle,
        "representative_bullets": representative,
    })

