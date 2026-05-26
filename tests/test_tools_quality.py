"""Tests for AI quality check tools."""

from __future__ import annotations

import json

from src.tools.quality import detect_ai_smell, detect_mirroring


def test_detect_ai_smell_clean_text() -> None:
    payload = json.dumps(
        {"text": "Built a distributed caching layer that cut p99 latency by 40ms."}
    )
    result = json.loads(detect_ai_smell.run(payload))
    assert "ai_smell_score" in result
    assert 0 <= result["ai_smell_score"] <= 100


def test_detect_ai_smell_buzzword_heavy() -> None:
    payload = json.dumps(
        {
            "text": "Leveraged synergies to spearhead innovative solutions and facilitate cross-functional collaboration."
        }
    )
    result = json.loads(detect_ai_smell.run(payload))
    assert result["ai_smell_score"] > 0
    assert len(result["detected_buzzwords"]) >= 1


def test_detect_mirroring_identical_texts() -> None:
    text = "Develop scalable microservices using Python and Kubernetes in production."
    payload = json.dumps({"job_text": text, "cv_text": text})
    result = json.loads(detect_mirroring.run(payload))
    assert result.get("similarity_score", 0) >= 0.0


def test_detect_mirroring_different_texts() -> None:
    payload = json.dumps(
        {
            "job_text": "We need a Java developer with Spring Boot expertise.",
            "cv_text": "Built ML pipelines using Python and Apache Spark.",
        }
    )
    result = json.loads(detect_mirroring.run(payload))
    assert result.get("similarity_score", 1.0) < 0.5
