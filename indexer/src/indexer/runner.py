"""Top-level orchestration — called by the CLI."""

from __future__ import annotations

import logging
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from common.base import INDEXER_VERSION, IndexMeta, StorePointer
from common.index import IndexStore
from common.media import MediaFile, MediaSource
from tqdm import tqdm

from indexer.batch import AdaptiveBatchController
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
    checkpoint_interval: int = 0,
    initial_batch_size: int = 1,
    max_batch_size: int = 32,
    adaptive_batch: bool = True,
) -> None:
    """Index media files and write them to the index store.

    When *folder* is given, only files under that subfolder of *media* are
    scanned.  An existing index is updated incrementally — files whose
    modification timestamp has not changed since the last run are skipped.
    If the stored ``indexer_version`` differs from
    :data:`~common.base.INDEXER_VERSION` a full rebuild is forced.

    Files are processed in batches.  *initial_batch_size* controls where to
    start; when *adaptive_batch* is True the controller grows or shrinks the
    batch based on measured throughput and available RAM.

    A checkpoint is written to the store after every batch when
    *checkpoint_interval* is 0 (the default), or every N files when > 0.
    Set to -1 to disable checkpoints entirely.
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
            initial_batch_size=initial_batch_size,
            max_batch_size=max_batch_size,
            adaptive_batch=adaptive_batch,
        )


def _run(
    media: MediaSource,
    store: StorePointer,
    caption_model: CaptionModel,
    index_store: IndexStore,
    local_tmp: Path,
    index_store_name: str,
    folder: str | None = None,
    checkpoint_interval: int = 0,
    initial_batch_size: int = 1,
    max_batch_size: int = 32,
    adaptive_batch: bool = True,
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
        "Starting indexing run from %s%s (batch_size=%d, adaptive=%s).",
        media.uri,
        f" (folder={folder!r})" if folder else "",
        initial_batch_size,
        adaptive_batch,
    )

    controller = AdaptiveBatchController(
        initial_size=initial_batch_size,
        max_size=max_batch_size,
        adaptive=adaptive_batch,
    )

    processed = 0
    pending: list[MediaFile] = []

    def _flush_batch(batch: list[MediaFile]) -> int:
        """Process one batch; return number of files successfully indexed."""
        return _process_batch(batch, caption_model, index_store, controller)

    def _write_checkpoint(n_processed: int) -> None:
        checkpoint_local = local_tmp / "db_checkpoint"
        index_store.checkpoint(checkpoint_local)
        store.put_dir(checkpoint_local, dest_name="db_checkpoint")
        logger.info("Checkpoint written after %d files.", n_processed)

    def _maybe_checkpoint_after_batch(prev_processed: int, new_processed: int) -> None:
        """Write checkpoints for every N-file boundary crossed in this batch.

        - checkpoint_interval < 0  → never
        - checkpoint_interval == 0 → always (once per batch)
        - checkpoint_interval > 0  → once per N-file boundary crossed
        """
        if checkpoint_interval < 0:
            return
        if checkpoint_interval == 0:
            _write_checkpoint(new_processed)
            return
        prev_mark = prev_processed // checkpoint_interval
        new_mark = new_processed // checkpoint_interval
        for _ in range(new_mark - prev_mark):
            _write_checkpoint(new_processed)

    for mf in tqdm(media.scan(subfolder=folder), desc="Indexing", unit="file"):
        logger.debug("Considering %s", mf.relative_path)

        if not force_reindex:
            existing = index_store.get_metadata(mf.relative_path)
            if existing is not None:
                stored_mtime = existing.get("file_mtime")
                try:
                    stored_mtime_f: float | None = float(stored_mtime) if stored_mtime else None
                except ValueError:
                    stored_mtime_f = None
                if (
                    stored_mtime_f is not None
                    and mf.mtime is not None
                    and abs(stored_mtime_f - mf.mtime) < 1.0
                ):
                    logger.debug("Skipping unchanged %s", mf.relative_path)
                    continue

        pending.append(mf)

        if len(pending) >= controller.current_size:
            t0 = time.monotonic()
            n = _flush_batch(pending)
            controller.record_batch(n_items=max(n, 1), elapsed_secs=time.monotonic() - t0)
            prev = processed
            processed += n
            pending = []
            _maybe_checkpoint_after_batch(prev, processed)

    # Flush remainder
    if pending:
        prev = processed
        n = _flush_batch(pending)
        processed += n
        _maybe_checkpoint_after_batch(prev, processed)

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


def _process_batch(
    mfs: list[MediaFile],
    caption_model: CaptionModel,
    index_store: IndexStore,
    controller: AdaptiveBatchController,
) -> int:
    """Open all files in *mfs*, caption them as a batch, and upsert.

    Returns the count of files successfully indexed.  On an OOM error the
    controller is notified and the batch is retried one file at a time so that
    no files are silently dropped.
    """
    try:
        return _do_batch(mfs, caption_model, index_store)
    except (MemoryError, RuntimeError) as exc:
        msg = str(exc).lower()
        if "out of memory" in msg or "cuda" in msg or isinstance(exc, MemoryError):
            logger.warning("OOM during batch of %d; retrying one-by-one. (%s)", len(mfs), exc)
            controller.on_oom()
            return _batch_single_fallback(mfs, caption_model, index_store)
        raise


def _do_batch(
    mfs: list[MediaFile],
    caption_model: CaptionModel,
    index_store: IndexStore,
) -> int:
    """Open all MediaFile contexts, call caption_batch, upsert results."""
    indexed = 0
    with ExitStack() as stack:
        opened: list[tuple[MediaFile, str]] = []
        for mf in mfs:
            try:
                stack.enter_context(mf)
                file_mtime = str(mf.mtime) if mf.mtime is not None else ""
                opened.append((mf, file_mtime))
            except Exception as exc:
                logger.warning("Could not open %s: %s", mf.relative_path, exc)

        if not opened:
            return 0

        open_mfs = [mf for mf, _ in opened]
        try:
            captions = caption_model.caption_batch(open_mfs)
        except Exception as exc:
            logger.warning("caption_batch failed for batch: %s", exc)
            return 0

        for (mf, file_mtime), caption in zip(opened, captions, strict=False):
            try:
                exif = extract_exif(mf)
                text = format_text(caption, exif)
                metadata: dict[str, str] = {
                    "caption": caption,
                    "relative_path": mf.relative_path,
                    "file_mtime": file_mtime,
                    **exif,
                }
                index_store.upsert(mf.relative_path, text, metadata)
                indexed += 1
            except Exception as exc:
                logger.warning("Skipping %s: %s", mf.relative_path, exc)

    return indexed


def _batch_single_fallback(
    mfs: list[MediaFile],
    caption_model: CaptionModel,
    index_store: IndexStore,
) -> int:
    """Process each file individually after an OOM batch failure."""
    indexed = 0
    for mf in mfs:
        with mf:
            try:
                file_mtime = str(mf.mtime) if mf.mtime is not None else ""
                caption = caption_model.caption(mf)
                exif = extract_exif(mf)
                text = format_text(caption, exif)
                metadata: dict[str, str] = {
                    "caption": caption,
                    "relative_path": mf.relative_path,
                    "file_mtime": file_mtime,
                    **exif,
                }
                index_store.upsert(mf.relative_path, text, metadata)
                indexed += 1
            except Exception as exc:
                logger.warning("Skipping %s: %s", mf.relative_path, exc)
    return indexed
