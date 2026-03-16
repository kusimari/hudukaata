"""IndexingRunner — orchestrates scan, skip, pipeline execution, and DB commit.

The runner owns all indexing orchestration:

  1. Clean up stale temp directories from aborted previous runs.
  2. Load the existing DB (or create an empty one), checking the indexer
     version to force a full rebuild when the schema changes.
  3. Scan the media source, skipping files whose mtime is unchanged.
  4. Drive the pipeline via the injected :class:`AdaptiveBatchRunner` or
     :class:`OneByOneRunner`, writing checkpoints periodically.
  5. Save the new DB and perform the atomic directory swap via
     :mod:`indexer.swap`.

The pipeline itself (stage methods, batching logic) lives in
:mod:`indexer.pipeline` and the indexer classes under
:mod:`indexer.indexers`.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from common.base import INDEXER_VERSION, IndexMeta, StorePointer
from common.index import IndexStore
from common.media import MediaSource
from tqdm import tqdm

from indexer.batch import AdaptiveBatchController
from indexer.indexers.blip2_sentok_exif_chroma import Blip2SentTokExifChromaIndexer
from indexer.models.base import CaptionModel
from indexer.pipeline import AdaptiveBatchRunner, BatchItem, OneByOneRunner, Pipeline
from indexer.swap import cleanup_stale_tmp, commit, prepare_temp_dir

logger = logging.getLogger(__name__)


class IndexingRunner:
    """Orchestrates a complete indexing run.

    Accepts any :class:`~indexer.pipeline.Pipeline`-compatible pipeline and
    delegates per-item processing to the injected *pipeline_runner*.

    Args:
        pipeline_runner: Drives the pipeline; either an
            :class:`~indexer.pipeline.AdaptiveBatchRunner` or a
            :class:`~indexer.pipeline.OneByOneRunner`.
        checkpoint_interval: Controls how often a DB snapshot is written to
            the store during the run.

            - ``< 0`` — disabled.
            - ``0``   — after every processed item.
            - ``> 0`` — once per N-item boundary.
    """

    def __init__(
        self,
        pipeline_runner: AdaptiveBatchRunner | OneByOneRunner,
        checkpoint_interval: int = 0,
    ) -> None:
        self._runner = pipeline_runner
        self._checkpoint_interval = checkpoint_interval

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        pipeline: Pipeline,
        media: MediaSource,
        store: StorePointer,
        index_store: IndexStore,
        index_store_name: str,
        folder: str | None = None,
    ) -> None:
        """Execute a full indexing run.

        Args:
            pipeline: Ordered list of stages to apply to each item.
            media: Source of media files to index.
            store: Pointer to the persistent store directory.
            index_store: Index store to read/write; must be uninitialised
                (neither :meth:`~common.index.IndexStore.load` nor
                :meth:`~common.index.IndexStore.create_empty` called yet).
            index_store_name: Human-readable name recorded in
                :class:`~common.base.IndexMeta`.
            folder: Optional subfolder within *media* to restrict scanning.
        """
        cleanup_stale_tmp(store)
        with tempfile.TemporaryDirectory(prefix="indexer_run_") as tmp_str:
            self._execute(
                pipeline,
                media,
                store,
                index_store,
                Path(tmp_str),
                index_store_name,
                folder,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute(
        self,
        pipeline: Pipeline,
        media: MediaSource,
        store: StorePointer,
        index_store: IndexStore,
        local_tmp: Path,
        index_store_name: str,
        folder: str | None,
    ) -> None:
        existing_created_at, force_reindex = self._setup_db(store, index_store)
        prepare_temp_dir(store, local_tmp)

        logger.info(
            "Starting indexing run from %s%s.",
            media.uri,
            f" (folder={folder!r})" if folder else "",
        )

        source = self._scan_and_skip(media, folder, index_store, force_reindex)

        for processed, _ in enumerate(self._runner.stream(pipeline, source), 1):
            self._maybe_checkpoint(processed, store, index_store, local_tmp)

        db_new_path = local_tmp / "db_new"
        index_store.save(db_new_path)
        logger.info("Saved new DB to %s", db_new_path)

        meta = IndexMeta.now(source=media.uri, index_store=index_store_name)
        meta.save(db_new_path / "index_meta.json")

        store.put_dir(db_new_path, dest_name="db_new")
        commit(store, local_tmp, existing_created_at)
        logger.info("DB swap complete.")

    def _setup_db(
        self,
        store: StorePointer,
        index_store: IndexStore,
    ) -> tuple[datetime | None, bool]:
        """Load or create the DB; return (created_at, force_reindex)."""
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

        return existing_created_at, force_reindex

    def _scan_and_skip(
        self,
        media: MediaSource,
        folder: str | None,
        index_store: IndexStore,
        force_reindex: bool,
    ) -> Iterator[BatchItem]:
        """Yield a :class:`~indexer.pipeline.BatchItem` for each file to process."""
        for mf in tqdm(media.scan(subfolder=folder), desc="Indexing", unit="file"):
            logger.debug("Considering %s", mf.relative_path)

            if not force_reindex:
                existing = index_store.get_metadata(mf.relative_path)
                if existing is not None:
                    stored_mtime = existing.get("file_mtime")
                    stored_mtime_f: float | None
                    try:
                        stored_mtime_f = float(stored_mtime) if stored_mtime else None
                    except ValueError:
                        stored_mtime_f = None
                    if (
                        stored_mtime_f is not None
                        and mf.mtime is not None
                        and abs(stored_mtime_f - mf.mtime) < 1.0
                    ):
                        logger.debug("Skipping unchanged %s", mf.relative_path)
                        continue

            yield BatchItem(media_file=mf)

    def _maybe_checkpoint(
        self,
        n_processed: int,
        store: StorePointer,
        index_store: IndexStore,
        local_tmp: Path,
    ) -> None:
        ci = self._checkpoint_interval
        if ci < 0:
            return
        if ci == 0:
            self._write_checkpoint(n_processed, store, index_store, local_tmp)
            return
        if n_processed % ci == 0:
            self._write_checkpoint(n_processed, store, index_store, local_tmp)

    def _write_checkpoint(
        self,
        n_processed: int,
        store: StorePointer,
        index_store: IndexStore,
        local_tmp: Path,
    ) -> None:
        checkpoint_local = local_tmp / "db_checkpoint"
        index_store.checkpoint(checkpoint_local)
        store.put_dir(checkpoint_local, dest_name="db_checkpoint")
        logger.info("Checkpoint written after %d files.", n_processed)


# ---------------------------------------------------------------------------
# Backward-compatible entry point (used by existing tests and CLI v1)
# ---------------------------------------------------------------------------


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

    Thin wrapper around :class:`IndexingRunner` that preserves the original
    function signature for backward compatibility with tests and the CLI.

    When *folder* is given, only files under that subfolder of *media* are
    scanned.  An existing index is updated incrementally — files whose
    modification timestamp has not changed since the last run are skipped.
    If the stored ``indexer_version`` differs from
    :data:`~common.base.INDEXER_VERSION` a full rebuild is forced.

    A checkpoint is written after every item when *checkpoint_interval* is 0,
    every N items when > 0, and never when < 0.
    """
    indexer = Blip2SentTokExifChromaIndexer(
        caption_model=caption_model,
        index_store=index_store,
    )
    ctrl = AdaptiveBatchController(
        initial_size=initial_batch_size,
        max_size=max_batch_size,
        adaptive=adaptive_batch,
    )
    runner = IndexingRunner(
        pipeline_runner=AdaptiveBatchRunner(ctrl),
        checkpoint_interval=checkpoint_interval,
    )
    runner.run(
        pipeline=indexer.pipeline(),
        media=media,
        store=store,
        index_store=index_store,
        index_store_name=index_store_name,
        folder=folder,
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
    """Internal entry point used by tests; accepts *local_tmp* explicitly."""
    indexer = Blip2SentTokExifChromaIndexer(
        caption_model=caption_model,
        index_store=index_store,
    )
    ctrl = AdaptiveBatchController(
        initial_size=initial_batch_size,
        max_size=max_batch_size,
        adaptive=adaptive_batch,
    )
    runner = IndexingRunner(
        pipeline_runner=AdaptiveBatchRunner(ctrl),
        checkpoint_interval=checkpoint_interval,
    )
    runner.run(
        pipeline=indexer.pipeline(),
        media=media,
        store=store,
        index_store=index_store,
        index_store_name=index_store_name,
        local_tmp=local_tmp,
        folder=folder,
    )
