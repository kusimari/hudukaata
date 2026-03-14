"""VectorStore abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any


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
    def query(
        self,
        vector: list[float],
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Return up to *n_results* documents closest to *vector*.

        Each result is a dict with at least an ``"id"`` key plus all stored
        metadata fields.
        """
        ...

    @abstractmethod
    def save(self, local_path: Path) -> None:
        """Persist DB to disk at local_path."""
        ...

    @abstractmethod
    def created_at(self, local_path: Path) -> datetime | None:
        """Return the creation timestamp recorded inside the DB, or None."""
        ...

    @abstractmethod
    def load_for_update(self, local_path: Path) -> None:
        """Copy DB to a temp dir, open it for read-write, and set up save().

        After this call the store is ready for :meth:`upsert`, :meth:`query`,
        :meth:`checkpoint`, and :meth:`save` — just like after
        :meth:`create_empty`.  The original at *local_path* is not modified.
        """
        ...

    @abstractmethod
    def upsert(
        self,
        id: str,
        vector: list[float],
        metadata: dict[str, str],
    ) -> None:
        """Add a document or replace it if *id* already exists."""
        ...

    @abstractmethod
    def get_metadata(self, id: str) -> dict[str, str] | None:
        """Return the stored metadata for *id*, or ``None`` if not present.

        Implementations may load all metadata once and cache it internally,
        or query the backing store per call — callers must not assume either
        strategy.
        """
        ...

    @abstractmethod
    def checkpoint(self, local_path: Path) -> None:
        """Copy the current working DB to *local_path* without finalising it.

        The store remains open and writable after this call.  The copy at
        *local_path* is a self-contained, queryable DB that survives a
        process kill.
        """
        ...
