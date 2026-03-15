"""IndexStore — abstract interface for reading and writing the media index.

The interface is intentionally free of vector or embedding concepts.
Implementations (e.g. ``ChromaCaptionIndexStore`` in the ``indexer`` package)
handle vectorization internally.

Linkage contract: :attr:`IndexResult.relative_path` equals
:attr:`~common.media.MediaFile.relative_path` — pass one directly to
:meth:`~common.media.MediaSource.getmedia` without any translation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class IndexResult:
    """A single result returned by :meth:`IndexStore.search`.

    The :attr:`relative_path` field is the stable identifier that links back to
    the media source::

        results = index_store.search("sunset photos", top_k=5)
        for r in results:
            with media_src.getmedia(r.relative_path) as mf:
                stream(mf.local_path)
    """

    id: str
    relative_path: str
    """Stable media identifier — pass directly to MediaSource.getmedia()."""
    caption: str
    score: float
    """Relevance score in [0, 1]; implementation-defined scale."""
    extra: dict[str, Any] = field(default_factory=dict)


class IndexStore(ABC):
    """Abstract index store — text in, :class:`IndexResult` out.

    All read and write operations accept plain text strings.  Vectorization,
    embedding model selection, and storage backend details are implementation
    concerns hidden inside each concrete subclass.
    """

    # --- read ---

    @abstractmethod
    def search(self, query: str, top_k: int) -> list[IndexResult]:
        """Return up to *top_k* results semantically matching *query*.

        Args:
            query: Free-text search query.
            top_k: Maximum number of results to return.

        Returns:
            List of :class:`IndexResult` ordered by relevance (best first).
        """

    @abstractmethod
    def get_metadata(self, id: str) -> dict[str, str] | None:
        """Return stored metadata for *id*, or ``None`` if not present."""

    # --- write ---

    @abstractmethod
    def add(self, id: str, text: str, metadata: dict[str, str]) -> None:
        """Index a new document.

        Args:
            id: Unique identifier (typically ``MediaFile.relative_path``).
            text: Human-readable text to embed and index.
            metadata: Arbitrary string key-value pairs stored alongside.
        """

    @abstractmethod
    def upsert(self, id: str, text: str, metadata: dict[str, str]) -> None:
        """Index a document, replacing it if *id* already exists."""

    def upsert_batch(
        self,
        ids: list[str],
        texts: list[str],
        metadatas: list[dict[str, str]],
    ) -> None:
        """Index a batch of documents, replacing any that already exist.

        Default implementation calls :meth:`upsert` once per item.
        Subclasses may override for a single vectorise-and-write pass.
        """
        for id_, text, meta in zip(ids, texts, metadatas, strict=True):
            self.upsert(id_, text, meta)

    # --- lifecycle ---

    @abstractmethod
    def load(self, local_path: Path) -> None:
        """Load an existing DB from disk at *local_path*."""

    @abstractmethod
    def create_empty(self) -> None:
        """Initialise a new, empty in-memory DB ready for writes."""

    @abstractmethod
    def save(self, local_path: Path) -> None:
        """Persist the current DB to *local_path*."""

    @abstractmethod
    def created_at(self, local_path: Path) -> datetime | None:
        """Return the creation timestamp recorded inside the DB, or ``None``."""

    @abstractmethod
    def load_for_update(self, local_path: Path) -> None:
        """Copy *local_path* to a temp dir and open it for read-write.

        The original DB is not modified.  After this call the store supports
        :meth:`upsert`, :meth:`get_metadata`, :meth:`checkpoint`, and
        :meth:`save`.
        """

    @abstractmethod
    def checkpoint(self, local_path: Path) -> None:
        """Write a self-contained snapshot of the current DB to *local_path*.

        The store remains open and writable after this call.
        """
