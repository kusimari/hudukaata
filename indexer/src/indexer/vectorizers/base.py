"""Vectorizer abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Vectorizer(ABC):
    @abstractmethod
    def vectorize(self, text: str) -> list[float]:
        """Embed text into a float vector."""
        ...

    def vectorize_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts, returning one vector per input in order.

        Default implementation calls :meth:`vectorize` once per text.
        Subclasses may override for a single model forward pass.
        """
        return [self.vectorize(t) for t in texts]

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector length."""
        ...
