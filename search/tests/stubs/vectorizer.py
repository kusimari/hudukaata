"""Stub vectorizer for search tests."""

from __future__ import annotations

from common.vectorizers.base import Vectorizer

_DIM = 8


class StubVectorizer(Vectorizer):
    def vectorize(self, text: str) -> list[float]:
        return [0.0] * _DIM

    @property
    def dimension(self) -> int:
        return _DIM
