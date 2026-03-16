"""Blip2SentTokExifChromaIndexer — caption + EXIF + sentence-transformer + ChromaDB.

This indexer assembles a :class:`~indexer.pipeline.Pipeline` whose stages are:

  open → caption (batched) → exif → format_text → upsert (batched) → close

Caption batching is handled by the pipeline runner; vectorisation is internal
to the :class:`~common.index.IndexStore` implementation (ChromaDB +
SentenceTransformer).
"""

from __future__ import annotations

import logging

from common.index import IndexStore
from common.media import MediaFile

from indexer.batch import AdaptiveBatchController
from indexer.exif import extract_exif
from indexer.models.base import CaptionModel
from indexer.pipeline import BatchItem, Pipeline, Stage
from indexer.text import format_text

logger = logging.getLogger(__name__)


class Blip2SentTokExifChromaIndexer:
    """Builds the caption-based indexing pipeline.

    Stage methods are bound to *caption_model* and *index_store* at
    construction time and wired together by :meth:`pipeline`.
    """

    def __init__(
        self,
        caption_model: CaptionModel,
        index_store: IndexStore,
    ) -> None:
        self._model = caption_model
        self._store = index_store

    # ------------------------------------------------------------------
    # Stage methods — all: list[BatchItem] → list[BatchItem]
    # ------------------------------------------------------------------

    def _open(self, items: list[BatchItem]) -> list[BatchItem]:
        """Enter each item's file context; drop items that cannot be opened."""
        result: list[BatchItem] = []
        for item in items:
            try:
                item._stack.enter_context(item.media_file)
                item.file_mtime = (
                    str(item.media_file.mtime) if item.media_file.mtime is not None else ""
                )
                result.append(item)
            except Exception as exc:
                logger.warning("Could not open %s: %s", item.media_file.relative_path, exc)
        return result

    def _caption(self, items: list[BatchItem]) -> list[BatchItem]:
        """Caption all items in one model forward pass; drop all on failure."""
        if not items:
            return items
        open_mfs: list[MediaFile] = [item.media_file for item in items]
        try:
            captions = self._model.caption_batch(open_mfs)
        except Exception as exc:
            logger.warning("caption_batch failed for batch of %d: %s", len(items), exc)
            for item in items:
                item._stack.close()
            return []
        for item, caption in zip(items, captions, strict=False):
            item.caption = caption
        return items

    def _exif(self, items: list[BatchItem]) -> list[BatchItem]:
        """Extract EXIF / media metadata per item; log and skip on error."""
        for item in items:
            try:
                item.exif = extract_exif(item.media_file)
            except Exception as exc:
                logger.warning(
                    "EXIF extraction failed for %s: %s", item.media_file.relative_path, exc
                )
        return items

    def _format_text(self, items: list[BatchItem]) -> list[BatchItem]:
        """Build the text string that will be vectorised and stored."""
        for item in items:
            item.text = format_text(item.caption, item.exif)
        return items

    def _upsert(self, items: list[BatchItem]) -> list[BatchItem]:
        """Write all items to the index store in one batch call."""
        if not items:
            return items
        ids = [item.media_file.relative_path for item in items]
        texts = [item.text for item in items]
        metadatas: list[dict[str, str]] = [
            {
                "caption": item.caption,
                "relative_path": item.media_file.relative_path,
                "file_mtime": item.file_mtime,
                **item.exif,
            }
            for item in items
        ]
        self._store.upsert_batch(ids, texts, metadatas)
        return items

    def _close(self, items: list[BatchItem]) -> list[BatchItem]:
        """Close each item's ExitStack, releasing its file handle."""
        for item in items:
            item._stack.close()
        return items

    # ------------------------------------------------------------------
    # Pipeline and controller factories
    # ------------------------------------------------------------------

    def pipeline(self) -> Pipeline:
        """Return the ordered list of :class:`~indexer.pipeline.Stage` objects."""
        return [
            Stage(self._open, batched=False),
            Stage(self._caption, batched=True),
            Stage(self._exif, batched=False),
            Stage(self._format_text, batched=False),
            Stage(self._upsert, batched=True),
            Stage(self._close, batched=False),
        ]

    def controller(
        self,
        initial_size: int = 1,
        max_size: int = 32,
        adaptive: bool = True,
    ) -> AdaptiveBatchController:
        """Return a fresh :class:`~indexer.batch.AdaptiveBatchController`."""
        return AdaptiveBatchController(
            initial_size=initial_size,
            max_size=max_size,
            adaptive=adaptive,
        )
