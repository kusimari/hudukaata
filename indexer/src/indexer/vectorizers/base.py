"""Vectorizer abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Vectorizer(ABC):
    @abstractmethod
    def vectorize(self, text: str) -> list[float]:
        """Embed text into a float vector."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector length."""
        ...
