"""IndexStore — generic abstract interface for reading and writing the media index.

The interface is parameterised by the item type *T*:

- :class:`CaptionItem` — text-based items; implementations vectorize the text internally.
- :class:`FaceItem` — face-embedding items; implementations store the vector directly.

Linkage contract: :attr:`IndexResult.relative_path` equals
:attr:`~common.media.MediaFile.relative_path` — pass one directly to
:meth:`~common.media.MediaSource.getmedia` without any translation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Item types
# ---------------------------------------------------------------------------


@dataclass
class CaptionItem:
    """A text caption to be vectorized and stored in a caption index."""

    text: str


@dataclass
class FaceItem:
    """A face embedding to be stored directly in a face index."""

    embedding: list[float]
    cluster_id: str


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class IndexResult(Generic[T]):
    """A single result returned by :meth:`IndexStore.search` or :meth:`IndexStore.list_all`.

    The :attr:`relative_path` field is the stable identifier that links back to
    the media source::

        results = index_store.search(CaptionItem(text="sunset photos"), top_k=5)
        for r in results:
            with media_src.getmedia(r.relative_path) as mf:
                stream(mf.local_path)
    """

    id: str
    relative_path: str
    """Stable media identifier — pass directly to MediaSource.getmedia()."""
    item: T
    score: float
    """Relevance score in [0, 1]; implementation-defined scale."""
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class IndexStore(ABC, Generic[T]):
    """Abstract generic index store — items in, :class:`IndexResult` out.

    *T* is either :class:`CaptionItem` or :class:`FaceItem`.  All read and
    write operations work with typed items; vectorization, embedding model
    selection, and storage backend details are implementation concerns hidden
    inside each concrete subclass.
    """

    # --- read ---

    @abstractmethod
    def search(self, query: T, top_k: int) -> list[IndexResult[T]]:
        """Return up to *top_k* results semantically matching *query*.

        Args:
            query: Typed item whose content is used as the search query.
            top_k: Maximum number of results to return.

        Returns:
            List of :class:`IndexResult` ordered by relevance (best first).
        """

    @abstractmethod
    def get_metadata(self, id: str) -> dict[str, str] | None:
        """Return stored metadata for *id*, or ``None`` if not present."""

    def list_all(self, top_k: int) -> list[IndexResult[T]]:
        """Return up to *top_k* items ordered by relevance (implementation-defined).

        Default implementation returns an empty list.  Override in stores
        where listing all entries makes sense (e.g. face cluster stores
        ordered by cluster frequency).
        """
        return []

    # --- write ---

    @abstractmethod
    def add(self, id: str, item: T, metadata: dict[str, str]) -> None:
        """Index a new document.

        Args:
            id: Unique identifier (typically ``MediaFile.relative_path``).
            item: Typed item to embed and index.
            metadata: Arbitrary string key-value pairs stored alongside.
        """

    @abstractmethod
    def upsert(self, id: str, item: T, metadata: dict[str, str]) -> None:
        """Index a document, replacing it if *id* already exists."""

    def upsert_batch(
        self,
        ids: list[str],
        items: list[T],
        metadatas: list[dict[str, str]],
    ) -> None:
        """Index a batch of documents, replacing any that already exist.

        Default implementation calls :meth:`upsert` once per item.
        Subclasses may override for a single vectorise-and-write pass.
        """
        for id_, item, meta in zip(ids, items, metadatas, strict=True):
            self.upsert(id_, item, meta)

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
