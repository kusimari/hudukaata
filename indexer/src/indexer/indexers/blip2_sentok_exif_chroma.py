"""Blip2SentTokExifChromaIndexer — caption + EXIF + sentence-transformer + ChromaDB.

This indexer assembles a :class:`~indexer.pipeline.Pipeline` whose stages are:

  open → caption (batched) → exif → format_text → upsert (batched) → close

Caption batching is handled by the pipeline runner; vectorisation is internal
to the :class:`~common.index.IndexStore` implementation (ChromaDB +
SentenceTransformer).
"""

from __future__ import annotations

import cytoolz as tz

from common.index import CaptionItem, IndexStore
from indexer.batch import AdaptiveBatchController
from indexer.models.base import CaptionModel
from indexer.pipeline import Pipeline
from indexer.stages import (
    caption_stage,
    close_stage,
    exif_stage,
    format_text_stage,
    open_stage,
    upsert_stage,
)


class Blip2SentTokExifChromaIndexer:
    """Builds the caption-based indexing pipeline.

    Stage functions are imported from :mod:`indexer.stages` and wired together
    by :meth:`pipeline` using ``tz.concat``.
    """

    def __init__(
        self,
        caption_model: CaptionModel,
        index_store: IndexStore[CaptionItem],
    ) -> None:
        self._model = caption_model
        self._store = index_store

    def pipeline(self) -> Pipeline:
        """Return the ordered list of :class:`~indexer.pipeline.Stage` objects."""
        return list(
            tz.concat(
                [
                    open_stage(),
                    caption_stage(self._model),
                    exif_stage(),
                    format_text_stage(),
                    upsert_stage(self._store),
                    close_stage(),
                ]
            )
        )

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
