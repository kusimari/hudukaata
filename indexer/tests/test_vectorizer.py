"""Tests for SentenceTransformerVectorizer — real model, no mocks."""

from __future__ import annotations

import pytest
from common.vectorizers.sentence_transformer import SentenceTransformerVectorizer


@pytest.fixture(scope="module")
def vectorizer() -> SentenceTransformerVectorizer:
    """Load the model once for the whole module (slow on first run)."""
    v = SentenceTransformerVectorizer()
    try:
        v.vectorize("warmup")  # force download / cache load
    except Exception as exc:
        pytest.skip(f"sentence-transformers model unavailable: {exc}")
    return v


class TestVectorize:
    def test_returns_list_of_floats(self, vectorizer):
        result = vectorizer.vectorize("hello world")
        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)

    def test_dimension_matches_property(self, vectorizer):
        result = vectorizer.vectorize("test sentence")
        assert len(result) == vectorizer.dimension

    def test_dimension_is_positive(self, vectorizer):
        assert vectorizer.dimension > 0

    def test_different_texts_produce_different_vectors(self, vectorizer):
        v1 = vectorizer.vectorize("a dog running in the park")
        v2 = vectorizer.vectorize("quantum chromodynamics in particle physics")
        assert v1 != v2

    def test_similar_texts_produce_closer_vectors(self, vectorizer):
        """Semantically similar sentences should be closer than unrelated ones."""
        import math

        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b, strict=True))
            mag_a = math.sqrt(sum(x * x for x in a))
            mag_b = math.sqrt(sum(x * x for x in b))
            return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0

        v_dog1 = vectorizer.vectorize("a dog playing fetch")
        v_dog2 = vectorizer.vectorize("a puppy running after a ball")
        v_physics = vectorizer.vectorize("quantum field theory equations")

        sim_related = cosine(v_dog1, v_dog2)
        sim_unrelated = cosine(v_dog1, v_physics)
        assert sim_related > sim_unrelated

    def test_empty_string_returns_vector(self, vectorizer):
        result = vectorizer.vectorize("")
        assert len(result) == vectorizer.dimension
