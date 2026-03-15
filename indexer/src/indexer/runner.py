"""Top-level orchestration — called by the CLI."""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path

from common.base import INDEXER_VERSION, IndexMeta, StorePointer
from common.index import IndexStore
from common.media import MediaSource
from tqdm import tqdm

from indexer.exif import extract_exif
from indexer.models.base import CaptionModel
from indexer.swap import cleanup_stale_tmp, commit, prepare_temp_dir
from indexer.text import format_text

logger = logging.getLogger(__name__)


def run(
    media: MediaSource,
    store: StorePointer,
    caption_model: CaptionModel,
    index_store: IndexStore,
    index_store_name: str,
    folder: str | None = None,
    checkpoint_interval: int = 100,
) -> None:
    """Index media files and write them to the index store.

    When *folder* is given, only files under that subfolder of *media* are
    scanned.  An existing index is updated incrementally — files whose
    modification timestamp has not changed since the last run are skipped.
    If the stored ``indexer_version`` differs from
    :data:`~common.base.INDEXER_VERSION` a full rebuild is forced.

    A checkpoint is written to the store every *checkpoint_interval* files so
    that a process kill leaves a usable partial index.
    """
    cleanup_stale_tmp(store)

    with tempfile.TemporaryDirectory(prefix="indexer_run_") as tmp_str:
        _run(
            media,
            store,
            caption_model,
            index_store,
            Path(tmp_str),
            index_store_name,
            folder=folder,
            checkpoint_interval=checkpoint_interval,
        )


def _run(
    media: MediaSource,
    store: StorePointer,
    caption_model: CaptionModel,
    index_store: IndexStore,
    local_tmp: Path,
    index_store_name: str,
    folder: str | None = None,
    checkpoint_interval: int = 100,
) -> None:
    existing_created_at: datetime | None = None
    force_reindex = False

    if store.has_dir("db"):
        with store.get_dir_ctx("db") as existing_db_path:
            existing_created_at = index_store.created_at(existing_db_path)
            meta_path = existing_db_path / "index_meta.json"
            if meta_path.exists():
                try:
                    existing_meta = IndexMeta.load(meta_path)
                    stored_version = existing_meta.indexer_version
                except ValueError:
                    stored_version = ""
            else:
                stored_version = ""

            if stored_version != INDEXER_VERSION:
                force_reindex = True
                logger.info(
                    "Indexer version changed (%r → %r); forcing full reindex.",
                    stored_version,
                    INDEXER_VERSION,
                )
                index_store.create_empty()
            else:
                logger.info(
                    "Existing DB found (created at %s); updating incrementally.",
                    existing_created_at,
                )
                index_store.load_for_update(existing_db_path)
    else:
        index_store.create_empty()

    prepare_temp_dir(store, local_tmp)

    logger.info(
        "Starting indexing run from %s%s.",
        media.uri,
        f" (folder={folder!r})" if folder else "",
    )

    processed = 0
    for mf in tqdm(media.scan(subfolder=folder), desc="Indexing", unit="file"):
        logger.debug("Considering %s", mf.relative_path)

        # Skip files that are already indexed and whose mtime is unchanged.
        if not force_reindex:
            existing = index_store.get_metadata(mf.relative_path)
            if existing is not None:
                stored_mtime = existing.get("file_mtime")
                if (
                    stored_mtime
                    and mf.mtime is not None
                    and abs(float(stored_mtime) - mf.mtime) < 1.0
                ):
                    logger.debug("Skipping unchanged %s", mf.relative_path)
                    continue

        with mf:
            try:
                file_mtime = str(mf.mtime) if mf.mtime is not None else ""
                caption = caption_model.caption(mf)
                exif = extract_exif(mf)
                text = format_text(caption, exif)
            except Exception as exc:
                logger.warning("Skipping %s: %s", mf.relative_path, exc)
                continue
            metadata: dict[str, str] = {
                "caption": caption,
                "relative_path": mf.relative_path,
                "file_mtime": file_mtime,
                **exif,
            }
            index_store.upsert(mf.relative_path, text, metadata)

        processed += 1
        if checkpoint_interval > 0 and processed % checkpoint_interval == 0:
            checkpoint_local = local_tmp / "db_checkpoint"
            index_store.checkpoint(checkpoint_local)
            store.put_dir(checkpoint_local, dest_name="db_checkpoint")
            logger.info("Checkpoint written after %d files.", processed)

    db_new_path = local_tmp / "db_new"
    index_store.save(db_new_path)
    logger.info("Saved new DB to %s", db_new_path)

    meta = IndexMeta.now(
        source=media.uri,
        index_store=index_store_name,
    )
    meta.save(db_new_path / "index_meta.json")

    store.put_dir(db_new_path, dest_name="db_new")
    commit(store, local_tmp, existing_created_at)
    logger.info("DB swap complete.")
