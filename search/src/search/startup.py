"""Server startup logic — fetch the index DB and load it into memory."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from common.meta import INDEX_META_FILE, IndexMeta
from common.pointer import StorePointer
from common.stores.base import VectorStore
from common.vectorizers.base import Vectorizer

from search.config import Settings
from search.plugins import resolve_vector_store, resolve_vectorizer

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """Holds the loaded vectorizer and vector store, ready to serve queries."""

    vectorizer: Vectorizer
    vector_store: VectorStore
    top_k: int
    # For rclone sources, holds the temp dir path that must be cleaned up on
    # shutdown (ChromaDB reads from disk throughout its lifetime, not only on
    # load(), so the directory must persist for the server's lifetime).
    _db_tmp_path: Path | None = field(default=None, repr=False)

    def cleanup(self) -> None:
        """Remove the rclone-downloaded DB temp directory, if any."""
        if self._db_tmp_path is not None:
            shutil.rmtree(self._db_tmp_path, ignore_errors=True)
            self._db_tmp_path = None


def load(settings: Settings) -> AppState:
    """Fetch the index DB from the store and return a ready :class:`AppState`.

    Steps:
    1. Parse the store URI into a :class:`~common.pointer.StorePointer`.
    2. Download (or reference) the ``db/`` directory locally.
    3. Read ``index_meta.json`` to discover which implementations were used.
    4. Instantiate and load the vector store from the local DB path.
    5. Instantiate the vectorizer (model loaded lazily on first query).

    Note on rclone sources: ``get_dir()`` is used rather than ``get_dir_ctx()``
    because ChromaDB's PersistentClient reads from the directory throughout its
    lifetime.  The temp dir is stored in ``AppState._db_tmp_path`` and must be
    cleaned up by calling ``AppState.cleanup()`` on server shutdown.
    """
    store_ptr = StorePointer.parse(settings.store)

    if not store_ptr.has_dir("db"):
        raise RuntimeError(
            f"No 'db' directory found at store {settings.store!r}. "
            "Run the indexer first to build the index."
        )

    logger.info("Fetching index DB from %s", settings.store)
    # get_dir() for file:// returns the actual path (no copy, no cleanup needed).
    # For rclone: it downloads to a temp dir that must persist for the lifetime
    # of the vector store client — see AppState._db_tmp_path.
    db_path = store_ptr.get_dir("db")
    db_tmp_path: Path | None = db_path if store_ptr.scheme == "rclone" else None

    try:
        meta = IndexMeta.load(db_path / INDEX_META_FILE)
        logger.info(
            "Index metadata: vectorizer=%r, vector_store=%r, indexed_at=%s",
            meta.vectorizer,
            meta.vector_store,
            meta.indexed_at,
        )
        vector_store = resolve_vector_store(meta.vector_store)
        vector_store.load(db_path)
    except Exception:
        # Clean up the downloaded dir if loading fails.
        if db_tmp_path is not None:
            shutil.rmtree(db_tmp_path, ignore_errors=True)
        raise

    vectorizer = resolve_vectorizer(meta.vectorizer)
    logger.info("Search server ready.")
    return AppState(
        vectorizer=vectorizer,
        vector_store=vector_store,
        top_k=settings.top_k,
        _db_tmp_path=db_tmp_path,
    )
