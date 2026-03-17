"""Blip2SentTokExifInsightfaceChromaIndexer — caption + faces + EXIF + ChromaDB.

This indexer extends the caption-only pipeline with face detection and
incremental clustering:

  open → caption (batched) → faces (batched) → exif
       → assign_clusters → format_text → upsert_captions (batched) → close

Face detection uses :class:`~indexer.models.insightface.InsightFaceModel`.
Clustering is done incrementally by :class:`~indexer.face_cluster.FaceClusterer`;
each detected face is compared to existing cluster centroids and either merged
or assigned to a new cluster.  The face store is updated as a side effect of
clustering so that subsequent runs pick up existing clusters.
"""

from __future__ import annotations

import logging

from common.index import CaptionItem, IndexStore
from common.media import MediaFile

from indexer.batch import AdaptiveBatchController
from indexer.exif import extract_exif
from indexer.face_cluster import FaceClusterer
from indexer.models.base import CaptionModel
from indexer.models.insightface import InsightFaceModel
from indexer.pipeline import BatchItem, Pipeline, Stage
from indexer.stores.chroma_face import ChromaFaceIndexStore
from indexer.text import format_text

logger = logging.getLogger(__name__)


class Blip2SentTokExifInsightfaceChromaIndexer:
    """Builds the face-aware indexing pipeline.

    Stage methods are bound at construction time and wired together by
    :meth:`pipeline`.

    Args:
        caption_model: Model used to caption images/video/audio.
        face_model: Model used to detect and embed faces in images.
        caption_store: Caption-based index store (receives text embeddings).
        face_store: Face cluster store (receives face centroids).
        cluster_threshold: Cosine similarity threshold for cluster assignment.
    """

    def __init__(
        self,
        caption_model: CaptionModel,
        face_model: InsightFaceModel,
        caption_store: IndexStore[CaptionItem],
        face_store: ChromaFaceIndexStore,
        cluster_threshold: float = 0.6,
    ) -> None:
        self._caption_model = caption_model
        self._face_model = face_model
        self._caption_store = caption_store
        self._face_store = face_store
        self._clusterer = FaceClusterer(face_store, threshold=cluster_threshold)

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
            captions = self._caption_model.caption_batch(open_mfs)
        except Exception as exc:
            logger.warning("caption_batch failed for batch of %d: %s", len(items), exc)
            for item in items:
                item._stack.close()
            return []
        for item, caption in zip(items, captions, strict=True):
            item.caption = caption
        return items

    def _faces(self, items: list[BatchItem]) -> list[BatchItem]:
        """Detect faces in one model forward pass; populates face_vectors."""
        if not items:
            return items
        open_mfs: list[MediaFile] = [item.media_file for item in items]
        try:
            all_face_vectors = self._face_model.detect_batch(open_mfs)
        except Exception as exc:
            logger.warning("detect_batch failed for batch of %d: %s", len(items), exc)
            return items  # continue without face data
        for item, face_vectors in zip(items, all_face_vectors, strict=True):
            item.face_vectors = face_vectors
        return items

    def _exif(self, items: list[BatchItem]) -> list[BatchItem]:
        """Extract EXIF / media metadata per item."""
        for item in items:
            try:
                item.exif = extract_exif(item.media_file)
            except Exception as exc:
                logger.warning(
                    "EXIF extraction failed for %s: %s", item.media_file.relative_path, exc
                )
        return items

    def _assign_clusters(self, items: list[BatchItem]) -> list[BatchItem]:
        """Assign each detected face vector to a cluster.

        Populates ``item.face_cluster_ids`` and updates the face store as a
        side effect (via :class:`~indexer.face_cluster.FaceClusterer`).
        """
        for item in items:
            cluster_ids: list[str] = []
            for vec in item.face_vectors:
                try:
                    cid = self._clusterer.assign(vec, item.media_file.relative_path)
                    cluster_ids.append(cid)
                except Exception as exc:
                    logger.warning(
                        "Cluster assignment failed for face in %s: %s",
                        item.media_file.relative_path,
                        exc,
                    )
            item.face_cluster_ids = cluster_ids
        return items

    def _format_text(self, items: list[BatchItem]) -> list[BatchItem]:
        """Build the text string that will be vectorised and stored."""
        for item in items:
            item.text = format_text(item.caption, item.exif)
        return items

    def _upsert_captions(self, items: list[BatchItem]) -> list[BatchItem]:
        """Write all items to the caption store in one batch call."""
        if not items:
            return items
        ids = [item.media_file.relative_path for item in items]
        caption_items = [CaptionItem(text=item.text) for item in items]
        metadatas: list[dict[str, str]] = [
            {
                "caption": item.caption,
                "relative_path": item.media_file.relative_path,
                "file_mtime": item.file_mtime,
                "face_cluster_ids": ",".join(item.face_cluster_ids),
                **item.exif,
            }
            for item in items
        ]
        self._caption_store.upsert_batch(ids, caption_items, metadatas)
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
            Stage(self._faces, batched=True),
            Stage(self._exif, batched=False),
            Stage(self._assign_clusters, batched=False),
            Stage(self._format_text, batched=False),
            Stage(self._upsert_captions, batched=True),
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
