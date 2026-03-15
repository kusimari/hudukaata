"""Server startup logic — fetch the index DB and load it into memory."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from common.base import INDEX_META_FILE, IndexMeta, StorePointer
from common.index import IndexStore
from common.media import MediaSource

from search.config import Settings
from search.plugins import resolve_index_store

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """Holds the loaded index store and media source, ready to serve queries."""

    index_store: IndexStore
    top_k: int
    media_src: MediaSource
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
    1. Parse the store URI into a :class:`~common.base.StorePointer`.
    2. Download (or reference) the ``db/`` directory locally.
    3. Read ``index_meta.json`` to discover which IndexStore implementation was used.
    4. Instantiate and load the index store from the local DB path.
    5. Parse the media URI for serving ``/media/{path}`` requests.

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
    # of the index store client — see AppState._db_tmp_path.
    db_path = store_ptr.get_dir("db")
    db_tmp_path: Path | None = db_path if store_ptr.scheme == "rclone" else None

    try:
        meta = IndexMeta.load(db_path / INDEX_META_FILE)
        logger.info(
            "Index metadata: index_store=%r, indexed_at=%s",
            meta.index_store,
            meta.indexed_at,
        )
        index_store = resolve_index_store(meta.index_store)
        index_store.load(db_path)
    except Exception:
        # Clean up the downloaded dir if loading fails.
        if db_tmp_path is not None:
            shutil.rmtree(db_tmp_path, ignore_errors=True)
        raise

    media_src = MediaSource.from_uri(settings.media)
    logger.info("Search server ready. Media root: %s", settings.media)
    return AppState(
        index_store=index_store,
        top_k=settings.top_k,
        media_src=media_src,
        _db_tmp_path=db_tmp_path,
    )
