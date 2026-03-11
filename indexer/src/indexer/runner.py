"""Top-level orchestration — called by the CLI."""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path

from common.meta import IndexMeta
from common.pointer import StorePointer
from common.stores.base import VectorStore
from common.vectorizers.base import Vectorizer
from tqdm import tqdm

from indexer.exif import extract_exif
from indexer.models.base import CaptionModel
from indexer.pointer import MediaPointer
from indexer.swap import cleanup_stale_tmp, commit, prepare_temp_dir
from indexer.text import format_text

logger = logging.getLogger(__name__)


def run(
    media: MediaPointer,
    store: StorePointer,
    caption_model: CaptionModel,
    vectorizer: Vectorizer,
    vector_store: VectorStore,
    vectorizer_name: str = "sentence-transformer",
    vector_store_name: str = "chroma",
) -> None:
    """Index all media files and write them to the vector store."""
    cleanup_stale_tmp(store)

    with tempfile.TemporaryDirectory(prefix="indexer_run_") as tmp_str:
        _run(
            media,
            store,
            caption_model,
            vectorizer,
            vector_store,
            Path(tmp_str),
            vectorizer_name,
            vector_store_name,
        )


def _run(
    media: MediaPointer,
    store: StorePointer,
    caption_model: CaptionModel,
    vectorizer: Vectorizer,
    vector_store: VectorStore,
    local_tmp: Path,
    vectorizer_name: str,
    vector_store_name: str,
) -> None:
    existing_created_at: datetime | None = None

    if store.has_dir("db"):
        with store.get_dir_ctx("db") as existing_db_path:
            existing_created_at = vector_store.created_at(existing_db_path)
        logger.info(
            "Existing DB found (created at %s); rebuilding from scratch.", existing_created_at
        )

    vector_store.create_empty()

    prepare_temp_dir(store, local_tmp)

    logger.info("Starting indexing run from %s.", media.uri)
    for mf in tqdm(media.scan(), desc="Indexing", unit="file"):
        logger.debug("Processing %s", mf.relative_path)
        with mf:
            try:
                caption = caption_model.caption(mf)
                exif = extract_exif(mf)
                text = format_text(caption, exif)
                vector = vectorizer.vectorize(text)
            except Exception as exc:
                logger.warning("Skipping %s: %s", mf.relative_path, exc)
                continue
            metadata: dict[str, str] = {
                "caption": caption,
                "relative_path": mf.relative_path,
                **exif,
            }
            vector_store.add(mf.relative_path, vector, metadata)

    db_new_path = local_tmp / "db_new"
    vector_store.save(db_new_path)
    logger.info("Saved new DB to %s", db_new_path)

    meta = IndexMeta.now(
        source=media.uri,
        vectorizer=vectorizer_name,
        vector_store=vector_store_name,
    )
    meta.save(db_new_path / "index_meta.json")

    store.put_dir(db_new_path, dest_name="db_new")
    commit(store, local_tmp, existing_created_at)
    logger.info("DB swap complete.")
