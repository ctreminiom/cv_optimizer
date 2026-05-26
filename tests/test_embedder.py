"""Tests for the local embedder and lru_cache model loading."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.search_pipeline import _load_local_model, _LocalEmbedder


def test_local_embedder_instances_are_independent() -> None:
    e1 = _LocalEmbedder()
    e2 = _LocalEmbedder()
    assert e1 is not e2
    assert not hasattr(_LocalEmbedder, "_model"), (
        "_LocalEmbedder must not have a class-level _model attribute. "
        "Model loading must use the module-level lru_cache instead."
    )


def test_load_local_model_is_callable() -> None:
    assert callable(_load_local_model)
    assert hasattr(_load_local_model, "cache_clear")


def test_local_embedder_returns_none_on_load_error() -> None:
    _load_local_model.cache_clear()
    with patch("src.search_pipeline._load_local_model", side_effect=Exception("no module")):
        e = _LocalEmbedder()
        result = e.embed(["text"])
        assert result is None


def test_two_embedder_instances_use_same_cached_model() -> None:
    _load_local_model.cache_clear()
    mock_model = MagicMock()
    mock_model.encode.return_value = [[0.5]]

    with patch("src.search_pipeline._load_local_model", return_value=mock_model):
        e1 = _LocalEmbedder()
        e2 = _LocalEmbedder()
        e1.embed(["a"])
        e2.embed(["b"])
        assert mock_model.encode.call_count == 2


def test_local_embedder_calls_encode_with_normalization() -> None:
    _load_local_model.cache_clear()
    mock_model = MagicMock()
    mock_model.encode.return_value = [[0.1, 0.2]]

    with patch("src.search_pipeline._load_local_model", return_value=mock_model):
        e = _LocalEmbedder()
        e.embed(["hello world"])
        mock_model.encode.assert_called_once_with(
            ["hello world"], convert_to_numpy=True, normalize_embeddings=True
        )
