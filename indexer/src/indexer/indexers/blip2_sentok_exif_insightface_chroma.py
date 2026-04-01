"""Blip2SentTokExifInsightfaceChromaIndexer — caption + faces + EXIF + ChromaDB.

This indexer extends the caption-only pipeline with face detection and
incremental clustering.  Caption, face detection, and EXIF extraction run
concurrently via :class:`~indexer.pipeline.ParallelStage`:

  open → ParallelStage([caption, faces, exif])
       → drop_failed → assign_clusters → format_text
       → upsert_captions (batched) → close

Face detection uses :class:`~indexer.models.insightface.InsightFaceModel`.
Clustering is done incrementally by :class:`~indexer.face_cluster.FaceClusterer`;
each detected face is compared to existing cluster centroids and either merged
or assigned to a new cluster.  The face store is updated as a side effect of
clustering so that subsequent runs pick up existing clusters.
"""

from __future__ import annotations

import cytoolz as tz
from common.index import CaptionItem, IndexStore

from indexer.batch import AdaptiveBatchController
from indexer.face_cluster import FaceClusterer
from indexer.models.base import CaptionModel
from indexer.models.insightface import InsightFaceModel
from indexer.pipeline import ParallelStage, Pipeline
from indexer.stages import (
    assign_clusters_stage,
    caption_stage,
    close_stage,
    drop_failed_stage,
    exif_stage,
    faces_stage,
    format_text_stage,
    open_stage,
    upsert_captions_stage,
)
from indexer.stores.chroma_face import ChromaFaceIndexStore


class Blip2SentTokExifInsightfaceChromaIndexer:
    """Builds the face-aware indexing pipeline.

    Stage functions are imported from :mod:`indexer.stages` and wired together
    by :meth:`pipeline` using ``tz.concat``.

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

    def pipeline(self) -> Pipeline:
        """Return the ordered list of :class:`~indexer.pipeline.Stage` objects."""
        parallel = ParallelStage(
            [
                caption_stage(self._caption_model)[0],
                faces_stage(self._face_model)[0],
                exif_stage()[0],
            ]
        )
        return list(
            tz.concat(
                [
                    open_stage(),
                    [parallel],
                    drop_failed_stage(),
                    assign_clusters_stage(self._clusterer),
                    format_text_stage(),
                    upsert_captions_stage(self._caption_store),
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
