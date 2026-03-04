"""VectorStore abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path


class VectorStore(ABC):
    @abstractmethod
    def load(self, local_path: Path) -> None:
        """Load existing DB from disk."""
        ...

    @abstractmethod
    def create_empty(self) -> None:
        """Initialise a new, empty DB in memory."""
        ...

    @abstractmethod
    def add(
        self,
        id: str,
        vector: list[float],
        metadata: dict[str, str],
    ) -> None:
        """Add a single document."""
        ...

    @abstractmethod
    def save(self, local_path: Path) -> None:
        """Persist DB to disk at local_path."""
        ...

    @abstractmethod
    def created_at(self, local_path: Path) -> datetime | None:
        """Return the creation timestamp recorded inside the DB, or None."""
        ...
