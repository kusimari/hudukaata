"""Pipeline primitives: Stage, ParallelStage, BatchItem, PrefetchSource, and runners.

A pipeline is a list of :class:`Stage` or :class:`ParallelStage` objects.
Each :class:`Stage` wraps a callable ``list[BatchItem] → list[BatchItem]``
and a ``batched`` flag.  A :class:`ParallelStage` groups data-independent
stages that are safe to run concurrently on the same batch.

Three runners are provided:

* :class:`OneByOneRunner` — passes every item through every stage
  individually.  No buffering.  Used in tests and as the OOM fallback.

* :class:`AdaptiveBatchRunner` — buffers items ahead of ``batched=True``
  stages, flushing when the buffer reaches ``controller.current_size``.
  Adjusts the size dynamically and falls back to one-by-one on OOM.
  Handles :class:`ParallelStage` by running sub-stages concurrently via a
  :class:`~concurrent.futures.ThreadPoolExecutor`.

:class:`PrefetchSource` wraps a source iterator and pre-loads PIL images
from disk in a background thread pool, overlapping disk IO with GPU
inference.  A bounded :class:`~queue.Queue` provides backpressure: the
background thread pauses whenever the queue is full and the pipeline has
not yet consumed the pre-loaded items.
"""

from __future__ import annotations

import logging
import queue
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import dataclass, field
from threading import Thread

from common.media import MediaFile

from indexer.batch import AdaptiveBatchController

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    """One step in the processing pipeline.

    *fn* must have the signature ``list[BatchItem] → list[BatchItem]``.
    When *batched* is ``True`` the :class:`AdaptiveBatchRunner` buffers items
    and calls *fn* with a full batch; when ``False`` it calls *fn* once per
    item.
    """

    fn: Callable[[list[BatchItem]], list[BatchItem]]
    batched: bool = False


@dataclass(frozen=True)
class ParallelStage:
    """A group of data-independent stages run concurrently on the same batch.

    All sub-stages must read from and write to non-overlapping
    :class:`BatchItem` fields so that concurrent mutation is safe.  Items
    dropped by *any* sub-stage are excluded from the output; their
    ``_stack`` context manager is closed before they are discarded.
    """

    stages: list[Stage]

    @property
    def batched(self) -> bool:
        """True if any sub-stage requests batch buffering."""
        return any(s.batched for s in self.stages)


Pipeline = list[Stage | ParallelStage]
"""Ordered list of :class:`Stage` and :class:`ParallelStage` objects."""


@dataclass
class BatchItem:
    """Mutable carrier that flows through every pipeline stage.

    Each field is populated by the stage responsible for it.  Stages must not
    read fields that have not yet been set by an upstream stage.
    """

    media_file: MediaFile
    _stack: ExitStack = field(default_factory=ExitStack, repr=False)
    file_mtime: str = ""
    caption: str = ""
    exif: dict[str, str] = field(default_factory=dict)
    text: str = ""
    face_vectors: list[list[float]] = field(default_factory=list)
    face_cluster_ids: list[str] = field(default_factory=list)
    # Pre-loaded PIL image set by PrefetchSource; cleared by caption_stage after use.
    # Typed as object to avoid importing PIL at module level.
    pil_image: object = field(default=None, repr=False)
    # Set by caption_stage on batch failure so drop_failed_stage can clean up.
    _failed: bool = field(default=False, repr=False)


# ---------------------------------------------------------------------------
# PrefetchSource
# ---------------------------------------------------------------------------


class PrefetchSource:
    """Wraps a source iterator and pre-loads PIL images in a background thread pool.

    While the pipeline processes batch K on the GPU, a :class:`ThreadPoolExecutor`
    loads images from disk for the upcoming items and places them in a bounded
    :class:`~queue.Queue`.  When the queue is full the background thread blocks,
    giving automatic backpressure as the adaptive controller changes batch size —
    no explicit tracking of ``current_size`` is required.

    Args:
        source: Upstream iterator of :class:`BatchItem` objects (media_file only).
        max_prefetch: Maximum number of pre-loaded items held in memory at once.
            Each RGB image occupies roughly ``width × height × 3`` bytes.
        max_workers: Number of parallel image-loading threads.
    """

    _SENTINEL: object = object()

    def __init__(
        self,
        source: Iterator[BatchItem],
        max_prefetch: int = 8,
        max_workers: int = 4,
    ) -> None:
        self._q: queue.Queue[object] = queue.Queue(maxsize=max_prefetch)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="prefetch")
        self._thread = Thread(target=self._run, args=(source,), daemon=True, name="prefetch-feed")
        self._thread.start()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_one(self, item: BatchItem) -> BatchItem:
        """Load the PIL image for *item* if it is an image file."""
        if item.media_file.media_type == "image":
            try:
                from PIL import Image

                item.pil_image = Image.open(item.media_file.local_path).convert("RGB")
            except Exception as exc:
                logger.warning("Prefetch failed for %s: %s", item.media_file.relative_path, exc)
        return item

    def _run(self, source: Iterator[BatchItem]) -> None:
        """Background thread: load images and fill the queue."""
        try:
            for item in source:
                future = self._executor.submit(self._load_one, item)
                # Block here when the queue is full — backpressure.
                self._q.put(future.result())
        finally:
            self._q.put(self._SENTINEL)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[BatchItem]:
        while True:
            item = self._q.get()
            if item is self._SENTINEL:
                break
            yield item  # type: ignore[misc]

    def close(self) -> None:
        """Shut down the executor and wait for the background thread to finish."""
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# OneByOneRunner
# ---------------------------------------------------------------------------


class OneByOneRunner:
    """Process every item through every stage individually.

    Passes a single-element list to every stage, regardless of the stage's
    ``batched`` flag.  No buffering, no batch-size control.  Suitable for
    tests and as the OOM fallback inside :class:`AdaptiveBatchRunner`.
    :class:`ParallelStage` sub-stages are run sequentially.
    """

    def stream(
        self,
        pipeline: Pipeline,
        source: Iterable[BatchItem],
    ) -> Iterator[BatchItem]:
        """Yield each :class:`BatchItem` after it has passed all stages."""
        s: Iterator[BatchItem] = iter(source)
        for step in pipeline:
            if isinstance(step, ParallelStage):
                s = self._each_parallel(step, s)
            else:
                s = self._each(step.fn, s)
        return s

    @staticmethod
    def _each(
        fn: Callable[[list[BatchItem]], list[BatchItem]],
        upstream: Iterator[BatchItem],
    ) -> Iterator[BatchItem]:
        for item in upstream:
            try:
                yield from fn([item])
            except Exception as exc:
                logger.warning("Stage dropped item %s: %s", item.media_file.relative_path, exc)

    @staticmethod
    def _each_parallel(
        ps: ParallelStage,
        upstream: Iterator[BatchItem],
    ) -> Iterator[BatchItem]:
        """Run each sub-stage sequentially per item (fallback / test path)."""
        for item in upstream:
            surviving = True
            for stage in ps.stages:
                try:
                    result = stage.fn([item])
                    if not result:
                        surviving = False
                        break
                except Exception as exc:
                    logger.warning("Stage dropped item %s: %s", item.media_file.relative_path, exc)
                    surviving = False
                    break
            if surviving:
                yield item
            else:
                item._stack.close()


# ---------------------------------------------------------------------------
# AdaptiveBatchRunner
# ---------------------------------------------------------------------------


def _is_oom(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return isinstance(exc, MemoryError) or "out of memory" in msg


def _intersect_survivors(
    items: list[BatchItem],
    results: list[list[BatchItem]],
) -> list[BatchItem]:
    """Return items present in every result list; close stacks of dropped items."""
    # Build a set of ids that survived every sub-stage.
    survivor_ids = set(id(item) for item in items)
    for result in results:
        survivor_ids &= set(id(item) for item in result)
    survivors = [item for item in items if id(item) in survivor_ids]
    # Close stacks for items that were dropped by at least one sub-stage.
    for item in items:
        if id(item) not in survivor_ids:
            item._stack.close()
    return survivors


class AdaptiveBatchRunner:
    """Process items in adaptive batches, timing flushes to tune batch size.

    Unbatched stages (``stage.batched=False``) receive one item at a time.
    Batched stages (``stage.batched=True``) receive a buffer of up to
    ``controller.current_size`` items per call.  After each flush the
    controller is updated with timing information so it can grow or shrink
    the batch for the next flush.

    :class:`ParallelStage` groups are flushed like a batched stage (using the
    group's ``batched`` property) and their sub-stages are executed concurrently
    via a :class:`~concurrent.futures.ThreadPoolExecutor`.

    On an OOM error the controller's ``on_oom()`` is called and the failing
    batch is retried one item at a time via :class:`OneByOneRunner`-style
    calls so that no items are silently dropped.
    """

    def __init__(self, controller: AdaptiveBatchController) -> None:
        self._ctrl = controller

    def stream(
        self,
        pipeline: Pipeline,
        source: Iterable[BatchItem],
    ) -> Iterator[BatchItem]:
        """Yield each :class:`BatchItem` after it has passed all stages."""
        s: Iterator[BatchItem] = iter(source)
        for step in pipeline:
            if isinstance(step, ParallelStage):
                s = self._parallel_stream(step, s)
            else:
                s = self._stage_stream(step, s)
        return s

    def _stage_stream(
        self,
        stage: Stage,
        upstream: Iterator[BatchItem],
    ) -> Iterator[BatchItem]:
        if not stage.batched:
            for item in upstream:
                try:
                    yield from stage.fn([item])
                except Exception as exc:
                    logger.warning("Stage dropped item %s: %s", item.media_file.relative_path, exc)
        else:
            buf: list[BatchItem] = []
            for item in upstream:
                buf.append(item)
                if len(buf) >= self._ctrl.current_size:
                    yield from self._flush(stage.fn, buf)
                    buf = []
            if buf:
                yield from self._flush(stage.fn, buf)

    def _parallel_stream(
        self,
        ps: ParallelStage,
        upstream: Iterator[BatchItem],
    ) -> Iterator[BatchItem]:
        """Buffer items and flush them through all sub-stages concurrently."""
        if not ps.batched:
            # All sub-stages are unbatched: process one item at a time.
            one = OneByOneRunner()
            yield from one._each_parallel(ps, upstream)
            return
        buf: list[BatchItem] = []
        for item in upstream:
            buf.append(item)
            if len(buf) >= self._ctrl.current_size:
                yield from self._flush_parallel(ps, buf)
                buf = []
        if buf:
            yield from self._flush_parallel(ps, buf)

    def _flush_parallel(
        self,
        ps: ParallelStage,
        buf: list[BatchItem],
    ) -> list[BatchItem]:
        t0 = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=len(ps.stages)) as ex:
                futures = {ex.submit(stage.fn, buf): stage for stage in ps.stages}
                results = [f.result() for f in as_completed(futures)]
            survivors = _intersect_survivors(buf, results)
            self._ctrl.record_batch(len(buf), time.monotonic() - t0)
            return survivors
        except (MemoryError, RuntimeError) as exc:
            if _is_oom(exc):
                logger.warning(
                    "OOM during parallel batch of %d; retrying one-by-one. (%s)", len(buf), exc
                )
                self._ctrl.on_oom()
                one = OneByOneRunner()
                return list(one._each_parallel(ps, iter(buf)))
            raise

    def _flush(
        self,
        fn: Callable[[list[BatchItem]], list[BatchItem]],
        buf: list[BatchItem],
    ) -> list[BatchItem]:
        t0 = time.monotonic()
        try:
            result = fn(buf)
            self._ctrl.record_batch(len(buf), time.monotonic() - t0)
            return result
        except (MemoryError, RuntimeError) as exc:
            if _is_oom(exc):
                logger.warning("OOM during batch of %d; retrying one-by-one. (%s)", len(buf), exc)
                self._ctrl.on_oom()
                results: list[BatchItem] = []
                for item in buf:
                    try:
                        results.extend(fn([item]))
                    except Exception as retry_exc:
                        logger.warning(
                            "Stage dropped item %s after OOM retry: %s",
                            item.media_file.relative_path,
                            retry_exc,
                        )
                return results
            raise
