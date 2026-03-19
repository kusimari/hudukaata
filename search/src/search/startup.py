"""Server startup logic — fetch the index DB and load it into memory."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.base import INDEX_META_FILE, IndexMeta, StorePointer
from common.index import CaptionItem, FaceItem, IndexStore
from common.media import MediaSource

from search.config import Settings
from search.plugins import resolve_index_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry: indexer_key → (caption_store_class, face_store_class | None)
# ---------------------------------------------------------------------------

_SERVE_REGISTRY: dict[str, dict[str, str | None]] = {
    "blip2-sentok-exif": {
        "caption_store": "indexer.stores.chroma_caption.ChromaCaptionIndexStore",
        "face_store": None,
    },
    "blip2-sentok-exif-insightface": {
        "caption_store": "indexer.stores.chroma_caption.ChromaCaptionIndexStore",
        "face_store": "indexer.stores.chroma_face.ChromaFaceIndexStore",
    },
}


def available_indexer_keys() -> list[str]:
    """Return the list of registered indexer keys."""
    return list(_SERVE_REGISTRY)


# ---------------------------------------------------------------------------
# AppState
# ---------------------------------------------------------------------------


@dataclass
class AppState:
    """Holds the loaded index store(s) and media source, ready to serve queries."""

    index_store: IndexStore[CaptionItem]
    top_k: int
    media_src: MediaSource
    face_store: IndexStore[FaceItem] | None = field(default=None)
    # For rclone sources, holds the temp dir path that must be cleaned up on
    # shutdown (ChromaDB reads from disk throughout its lifetime, not only on
    # load(), so the directory must persist for the server's lifetime).
    _db_tmp_path: Path | None = field(default=None, repr=False)

    def cleanup(self) -> None:
        """Remove the rclone-downloaded DB temp directory, if any."""
        if self._db_tmp_path is not None:
            shutil.rmtree(self._db_tmp_path, ignore_errors=True)
            self._db_tmp_path = None


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------


def load(settings: Settings) -> AppState:
    """Fetch the index DB from the store and return a ready :class:`AppState`.

    Validates that the stored ``index_meta.json`` matches the requested
    *indexer_key*.  Raises :class:`RuntimeError` if the face store is required
    by the indexer key but is absent or mismatched.

    Note on rclone sources: ``get_dir()`` is used rather than ``get_dir_ctx()``
    because ChromaDB's PersistentClient reads from the directory throughout its
    lifetime.  The temp dir is stored in ``AppState._db_tmp_path`` and must be
    cleaned up by calling ``AppState.cleanup()`` on server shutdown.
    """
    indexer_key = settings.indexer_key
    if indexer_key not in _SERVE_REGISTRY:
        raise RuntimeError(
            f"Unknown indexer key {indexer_key!r}. Available: {', '.join(sorted(_SERVE_REGISTRY))}"
        )
    registry_entry = _SERVE_REGISTRY[indexer_key]
    caption_store_class = registry_entry["caption_store"]
    face_store_class = registry_entry["face_store"]

    store_ptr = StorePointer.parse(settings.store)

    if not store_ptr.has_dir("db"):
        raise RuntimeError(
            f"No 'db' directory found at store {settings.store!r}. "
            "Run the indexer first to build the index."
        )

    logger.info("Fetching index DB from %s", settings.store)
    db_path = store_ptr.get_dir("db")
    db_tmp_path: Path | None = db_path if store_ptr.scheme == "rclone" else None

    try:
        meta = IndexMeta.load(db_path / INDEX_META_FILE)
        logger.info(
            "Index metadata: index_store=%r, indexed_at=%s",
            meta.index_store,
            meta.indexed_at,
        )

        # Validate face store availability when required.
        if face_store_class is not None:
            if meta.face_store is None:
                raise RuntimeError(
                    f"Indexer key {indexer_key!r} requires a face store, but "
                    f"index_meta.json at {db_path} has no 'face_store' field. "
                    "Re-index with a face-aware indexer first."
                )
            if not meta.face_store.endswith("ChromaFaceIndexStore"):
                raise RuntimeError(
                    f"Indexer key {indexer_key!r} expects ChromaFaceIndexStore but "
                    f"index_meta.json records {meta.face_store!r}."
                )

        index_store: IndexStore[Any] = resolve_index_store(str(caption_store_class))
        index_store.load(db_path)

        face_store: IndexStore[FaceItem] | None = None
        if face_store_class is not None:
            face_store = resolve_index_store(str(face_store_class))
            face_store.load(db_path)

    except Exception:
        if db_tmp_path is not None:
            shutil.rmtree(db_tmp_path, ignore_errors=True)
        raise

    media_src = MediaSource.from_uri(settings.media)
    logger.info("Search server ready. Media root: %s", settings.media)
    return AppState(
        index_store=index_store,
        face_store=face_store,
        top_k=settings.top_k,
        media_src=media_src,
        _db_tmp_path=db_tmp_path,
    )
