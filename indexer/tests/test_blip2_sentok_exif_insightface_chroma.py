"""Tests for Blip2SentTokExifInsightfaceChromaIndexer stage methods."""

from __future__ import annotations

from unittest.mock import MagicMock

from common.media import MediaFile

from indexer.indexers.blip2_sentok_exif_insightface_chroma import (
    Blip2SentTokExifInsightfaceChromaIndexer,
)
from indexer.pipeline import BatchItem
from indexer.stores.chroma_face import ChromaFaceIndexStore
from tests.stubs.caption_model import StubCaptionModel
from tests.stubs.index_store import StubIndexStore
from tests.stubs.insightface import StubInsightFaceModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_mf(path: str = "a.jpg", mtime: float | None = 1234.0) -> MagicMock:
    mf = MagicMock(spec=MediaFile)
    mf.relative_path = path
    mf.mtime = mtime
    mf.media_type = "image"
    return mf


def _item(path: str = "a.jpg", mtime: float | None = 1234.0) -> BatchItem:
    return BatchItem(media_file=_mock_mf(path, mtime))


def _make_face_store() -> ChromaFaceIndexStore:
    store = ChromaFaceIndexStore()
    store.create_empty()
    return store


def _indexer(
    caption_model: StubCaptionModel | None = None,
    face_model: StubInsightFaceModel | None = None,
    caption_store: StubIndexStore | None = None,
    face_store: ChromaFaceIndexStore | None = None,
    faces_per_image: int = 1,
) -> Blip2SentTokExifInsightfaceChromaIndexer:
    return Blip2SentTokExifInsightfaceChromaIndexer(
        caption_model=caption_model or StubCaptionModel(),
        face_model=face_model or StubInsightFaceModel(faces_per_image=faces_per_image),
        caption_store=caption_store or StubIndexStore(),
        face_store=face_store or _make_face_store(),
    )


# ---------------------------------------------------------------------------
# _faces stage
# ---------------------------------------------------------------------------


class TestFacesStage:
    def test_populates_face_vectors(self) -> None:
        item = _item("img.jpg")
        item.media_file.__enter__ = lambda s: s
        item.media_file.__exit__ = lambda s, *a: None
        item._stack.enter_context(item.media_file)

        idx = _indexer(faces_per_image=2)
        result = idx._faces([item])

        assert len(result) == 1
        assert len(result[0].face_vectors) == 2
        assert len(result[0].face_vectors[0]) == 512

    def test_non_image_yields_empty_face_vectors(self) -> None:
        item = _item("audio.mp3")
        item.media_file.media_type = "audio"
        item.media_file.__enter__ = lambda s: s
        item.media_file.__exit__ = lambda s, *a: None
        item._stack.enter_context(item.media_file)

        idx = _indexer(faces_per_image=2)
        result = idx._faces([item])

        assert result[0].face_vectors == []

    def test_empty_input_passthrough(self) -> None:
        assert _indexer()._faces([]) == []


# ---------------------------------------------------------------------------
# _assign_clusters stage
# ---------------------------------------------------------------------------


class TestAssignClustersStage:
    def test_assigns_cluster_ids_for_each_face(self) -> None:
        face_store = _make_face_store()
        idx = _indexer(face_store=face_store, faces_per_image=2)

        item = _item("img.jpg")
        item.face_vectors = [[0.1] * 512, [0.9] * 512]

        result = idx._assign_clusters([item])

        assert len(result[0].face_cluster_ids) == 2

    def test_no_faces_yields_empty_cluster_ids(self) -> None:
        idx = _indexer()
        item = _item()
        item.face_vectors = []
        result = idx._assign_clusters([item])
        assert result[0].face_cluster_ids == []


# ---------------------------------------------------------------------------
# _upsert_captions stage
# ---------------------------------------------------------------------------


class TestUpsertCaptionsStage:
    def test_stores_face_cluster_ids_in_metadata(self) -> None:
        caption_store = StubIndexStore()
        caption_store.create_empty()
        idx = _indexer(caption_store=caption_store)

        item = _item("img.jpg")
        item.caption = "a person"
        item.text = "a person"
        item.file_mtime = "1234.0"
        item.exif = {}
        item.face_cluster_ids = ["uuid-1", "uuid-2"]

        idx._upsert_captions([item])

        meta = caption_store.get_metadata("img.jpg")
        assert meta is not None
        assert meta["face_cluster_ids"] == "uuid-1,uuid-2"


# ---------------------------------------------------------------------------
# pipeline shape
# ---------------------------------------------------------------------------


class TestPipeline:
    def test_pipeline_has_eight_stages(self) -> None:
        pipeline = _indexer().pipeline()
        assert len(pipeline) == 8

    def test_pipeline_stages_are_callable(self) -> None:
        for stage in _indexer().pipeline():
            assert callable(stage.fn)
