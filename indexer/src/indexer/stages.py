"""Stage factories for the indexing pipeline.

Every factory returns a ``list[Stage]`` (a mini-pipeline) so callers can use
``tz.concat`` to compose the full pipeline without caring whether a logical
step expands to one or more physical :class:`~indexer.pipeline.Stage` objects.

Shared stages (``open_stage``, ``caption_stage``, ``exif_stage``,
``format_text_stage``, ``close_stage``) are used by every indexer.
Specialised stages (``faces_stage``, ``assign_clusters_stage``,
``upsert_captions_stage``, ``upsert_stage``) are imported only by the indexers
that need them.
"""

from __future__ import annotations

import logging

from common.index import CaptionItem, IndexStore

from indexer.exif import extract_exif
from indexer.face_cluster import FaceClusterer
from indexer.models.base import CaptionModel
from indexer.models.insightface import InsightFaceModel
from indexer.pipeline import BatchItem, Stage
from indexer.text import format_text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared stages
# ---------------------------------------------------------------------------


def open_stage() -> list[Stage]:
    """Enter each item's file context; drop items that cannot be opened."""

    def _try_open(item: BatchItem) -> BatchItem | None:
        try:
            item._stack.enter_context(item.media_file)
            item.file_mtime = (
                str(item.media_file.mtime) if item.media_file.mtime is not None else ""
            )
            return item
        except Exception as exc:
            logger.warning("Could not open %s: %s", item.media_file.relative_path, exc)
            return None

    def fn(items: list[BatchItem]) -> list[BatchItem]:
        return [item for item in map(_try_open, items) if item is not None]

    return [Stage(fn, batched=False)]


def caption_stage(model: CaptionModel) -> list[Stage]:
    """Caption all items in one model forward pass; drop all on failure."""

    def fn(items: list[BatchItem]) -> list[BatchItem]:
        if not items:
            return items
        mfs = [item.media_file for item in items]
        try:
            captions = model.caption_batch(mfs)
            for item, caption in zip(items, captions, strict=True):
                item.caption = caption
        except Exception as exc:
            logger.warning("caption_batch failed for batch of %d: %s", len(items), exc)
            for item in items:
                item._stack.close()
            return []
        return items

    return [Stage(fn, batched=True)]


def exif_stage() -> list[Stage]:
    """Extract EXIF / media metadata per item; log and skip on error."""

    def _apply(item: BatchItem) -> BatchItem:
        try:
            item.exif = extract_exif(item.media_file)
        except Exception as exc:
            logger.warning("EXIF extraction failed for %s: %s", item.media_file.relative_path, exc)
        return item

    def fn(items: list[BatchItem]) -> list[BatchItem]:
        return list(map(_apply, items))

    return [Stage(fn, batched=False)]


def format_text_stage() -> list[Stage]:
    """Build the text string that will be vectorised and stored."""

    def _apply(item: BatchItem) -> BatchItem:
        item.text = format_text(item.caption, item.exif)
        return item

    def fn(items: list[BatchItem]) -> list[BatchItem]:
        return list(map(_apply, items))

    return [Stage(fn, batched=False)]


def close_stage() -> list[Stage]:
    """Close each item's ExitStack, releasing its file handle."""

    def _apply(item: BatchItem) -> BatchItem:
        item._stack.close()
        return item

    def fn(items: list[BatchItem]) -> list[BatchItem]:
        return list(map(_apply, items))

    return [Stage(fn, batched=False)]


# ---------------------------------------------------------------------------
# Face-aware stages
# ---------------------------------------------------------------------------


def faces_stage(model: InsightFaceModel) -> list[Stage]:
    """Detect faces in one model forward pass; populates face_vectors."""

    def fn(items: list[BatchItem]) -> list[BatchItem]:
        if not items:
            return items
        mfs = [item.media_file for item in items]
        try:
            all_face_vectors = model.detect_batch(mfs)
        except Exception as exc:
            logger.warning("detect_batch failed for batch of %d: %s", len(items), exc)
            return items  # continue without face data
        for item, face_vectors in zip(items, all_face_vectors, strict=True):
            item.face_vectors = face_vectors
        return items

    return [Stage(fn, batched=True)]


def assign_clusters_stage(clusterer: FaceClusterer) -> list[Stage]:
    """Assign each detected face vector to a cluster; populates face_cluster_ids."""

    def _apply(item: BatchItem) -> BatchItem:
        cluster_ids: list[str] = []
        for vec in item.face_vectors:
            try:
                cid = clusterer.assign(vec, item.media_file.relative_path)
                cluster_ids.append(cid)
            except Exception as exc:
                logger.warning(
                    "Cluster assignment failed for face in %s: %s",
                    item.media_file.relative_path,
                    exc,
                )
        item.face_cluster_ids = cluster_ids
        return item

    def fn(items: list[BatchItem]) -> list[BatchItem]:
        return list(map(_apply, items))

    return [Stage(fn, batched=False)]


def upsert_captions_stage(store: IndexStore[CaptionItem]) -> list[Stage]:
    """Write all items to the caption store, including face cluster ids."""

    def fn(items: list[BatchItem]) -> list[BatchItem]:
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
        store.upsert_batch(ids, caption_items, metadatas)
        return items

    return [Stage(fn, batched=True)]
