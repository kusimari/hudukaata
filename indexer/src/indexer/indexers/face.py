"""FaceIndexer — extends Blip2SentTokExifChromaIndexer with face detection.

Splices two face-specific stages before the final ``close`` stage:

  … → upsert → extract_faces (batched) → upsert_faces (batched) → close

Face vectors are stored in a separate :class:`~common.index.IndexStore`
(``face_store``) while the caption store is inherited from the base class.
"""

from __future__ import annotations

import logging
from typing import Protocol

from common.index import IndexStore
from common.media import MediaFile

from indexer.indexers.blip2_sentok_exif_chroma import Blip2SentTokExifChromaIndexer
from indexer.models.base import CaptionModel
from indexer.pipeline import BatchItem, Pipeline, Stage

logger = logging.getLogger(__name__)


class FaceModel(Protocol):
    """Minimal protocol for a face-detection / embedding model."""

    def embed_batch(self, mfs: list[MediaFile]) -> list[list[list[float]]]:
        """Return a list of face-vector lists, one list per input image.

        Each inner list contains zero or more face embedding vectors for
        the corresponding image.
        """
        ...


class FaceIndexer(Blip2SentTokExifChromaIndexer):
    """Caption + face indexing pipeline.

    Inherits all seven caption stages from the base class and splices two
    face stages before ``_close``.
    """

    def __init__(
        self,
        caption_model: CaptionModel,
        index_store: IndexStore,
        face_model: FaceModel,
        face_store: IndexStore,
    ) -> None:
        super().__init__(caption_model=caption_model, index_store=index_store)
        self._face_model = face_model
        self._face_store = face_store

    # ------------------------------------------------------------------
    # Face-specific stages
    # ------------------------------------------------------------------

    def _extract_faces(self, items: list[BatchItem]) -> list[BatchItem]:
        """Run the face model; populate ``item.face_vectors`` per item."""
        if not items:
            return items
        try:
            all_vectors = self._face_model.embed_batch([item.media_file for item in items])
        except Exception as exc:
            logger.warning("Face embed_batch failed for batch of %d: %s", len(items), exc)
            for item in items:
                item.face_vectors = []
            return items
        for item, vectors in zip(items, all_vectors, strict=False):
            item.face_vectors = vectors
        return items

    def _upsert_faces(self, items: list[BatchItem]) -> list[BatchItem]:
        """Write detected faces to the face store."""
        for item in items:
            for i, _vector in enumerate(item.face_vectors):
                face_id = f"{item.media_file.relative_path}__face_{i}"
                self._face_store.upsert(
                    face_id,
                    "",
                    {
                        "relative_path": item.media_file.relative_path,
                        "face_index": str(i),
                    },
                )
        return items

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def pipeline(self) -> Pipeline:
        """Caption pipeline with face stages inserted before ``_close``."""
        base = super().pipeline()
        *body, close = base  # close is always the last stage
        return body + [
            Stage(self._extract_faces, batched=True),
            Stage(self._upsert_faces, batched=False),
            close,
        ]
