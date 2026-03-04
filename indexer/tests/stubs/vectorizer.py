"""Stub vectorizer — returns a fixed-length zero vector."""

from __future__ import annotations

from indexer.vectorizers.base import Vectorizer

_DIM = 8


class StubVectorizer(Vectorizer):
    def vectorize(self, text: str) -> list[float]:
        return [0.0] * _DIM

    @property
    def dimension(self) -> int:
        return _DIM
