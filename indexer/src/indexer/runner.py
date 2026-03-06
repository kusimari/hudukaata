"""Top-level orchestration — called by the CLI."""

from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from indexer.exif import extract_exif
from indexer.models.base import CaptionModel
from indexer.pointer import MediaPointer
from indexer.scanner import scan
from indexer.stores.base import VectorStore
from indexer.swap import cleanup_stale_tmp, commit, prepare_temp_dir
from indexer.vectorizers.base import Vectorizer
from indexer.vectorizers.sentence_transformer import format_text

logger = logging.getLogger(__name__)


def run(
    media: MediaPointer,
    store: MediaPointer,
    caption_model: CaptionModel,
    vectorizer: Vectorizer,
    vector_store: VectorStore,
) -> None:
    """Index all media files and write them to the vector store."""
    cleanup_stale_tmp(store)

    local_tmp = Path(tempfile.mkdtemp(prefix="indexer_run_"))
    try:
        _run(media, store, caption_model, vectorizer, vector_store, local_tmp)
    finally:
        shutil.rmtree(local_tmp, ignore_errors=True)


def _run(
    media: MediaPointer,
    store: MediaPointer,
    caption_model: CaptionModel,
    vectorizer: Vectorizer,
    vector_store: VectorStore,
    local_tmp: Path,
) -> None:
    existing_created_at: datetime | None = None

    if store.has_dir("db"):
        # For rclone pointers, get_dir downloads the DB to a temp dir that
        # the caller must clean up. We read created_at only; the DB itself
        # is always rebuilt from scratch (no incremental indexing).
        _existing_db_path = store.get_dir("db")
        try:
            existing_created_at = vector_store.created_at(_existing_db_path)
        finally:
            if store.scheme == "rclone":
                shutil.rmtree(_existing_db_path, ignore_errors=True)
        logger.info(
            "Existing DB found (created at %s); rebuilding from scratch.", existing_created_at
        )

    vector_store.create_empty()

    prepare_temp_dir(store, local_tmp)

    media_files = list(scan(media))
    logger.info("Found %d media files to index.", len(media_files))

    for mf in tqdm(media_files, desc="Indexing", unit="file"):
        logger.debug("Processing %s", mf.relative_path)
        try:
            caption = caption_model.caption(mf)
            exif = extract_exif(mf)
            text = format_text(caption, exif)
            vector = vectorizer.vectorize(text)
        except Exception as exc:
            logger.warning("Skipping %s: %s", mf.relative_path, exc)
            continue
        metadata: dict[str, str] = {"caption": caption, **exif}
        vector_store.add(mf.relative_path, vector, metadata)

    db_new_path = local_tmp / "db_new"
    vector_store.save(db_new_path)
    logger.info("Saved new DB to %s", db_new_path)

    store.put_dir(db_new_path, dest_name="db_new")
    commit(store, local_tmp, existing_created_at)
    logger.info("DB swap complete.")
