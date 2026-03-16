"""Pipeline primitives: Stage, BatchItem, and pipeline runner classes.

A pipeline is a list of :class:`Stage` objects.  Each stage wraps a callable
with the signature ``list[BatchItem] → list[BatchItem]`` and a ``batched``
flag.  Runners consume a source of :class:`BatchItem` objects and yield
processed items as a stream.

Two runners are provided:

* :class:`OneByOneRunner` — passes every item through every stage
  individually.  No buffering.  Used in tests and as the OOM fallback.

* :class:`AdaptiveBatchRunner` — buffers items ahead of ``batched=True``
  stages, flushing when the buffer reaches ``controller.current_size``.
  Adjusts the size dynamically and falls back to one-by-one on OOM.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field

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


Pipeline = list[Stage]
"""A list of :class:`Stage` objects executed left-to-right."""


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


# ---------------------------------------------------------------------------
# OneByOneRunner
# ---------------------------------------------------------------------------


class OneByOneRunner:
    """Process every item through every stage individually.

    Passes a single-element list to every stage, regardless of the stage's
    ``batched`` flag.  No buffering, no batch-size control.  Suitable for
    tests and as the OOM fallback inside :class:`AdaptiveBatchRunner`.
    """

    def stream(
        self,
        pipeline: Pipeline,
        source: Iterable[BatchItem],
    ) -> Iterator[BatchItem]:
        """Yield each :class:`BatchItem` after it has passed all stages.

        ``stage.batched`` is intentionally ignored — every stage receives a
        single-element list regardless of the flag.  This is the correct
        behaviour for the OOM fallback and for testing individual stages.
        """
        s: Iterator[BatchItem] = iter(source)
        for stage in pipeline:
            s = self._each(stage.fn, s)
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


# ---------------------------------------------------------------------------
# AdaptiveBatchRunner
# ---------------------------------------------------------------------------


def _is_oom(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return isinstance(exc, MemoryError) or "out of memory" in msg


class AdaptiveBatchRunner:
    """Process items in adaptive batches, timing flushes to tune batch size.

    Unbatched stages (``stage.batched=False``) receive one item at a time.
    Batched stages (``stage.batched=True``) receive a buffer of up to
    ``controller.current_size`` items per call.  After each flush the
    controller is updated with timing information so it can grow or shrink
    the batch for the next flush.

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
        for stage in pipeline:
            s = self._stage_stream(stage, s)
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
