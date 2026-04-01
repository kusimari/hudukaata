"""Tests for Blip2SentTokExifInsightfaceChromaIndexer stage methods."""

from __future__ import annotations

from unittest.mock import MagicMock

from common.media import MediaFile

from indexer.indexers.blip2_sentok_exif_insightface_chroma import (
    Blip2SentTokExifInsightfaceChromaIndexer,
)
from indexer.pipeline import BatchItem
from indexer.stages import assign_clusters_stage, faces_stage, upsert_captions_stage
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
# faces_stage
# ---------------------------------------------------------------------------


class TestFacesStage:
    def test_populates_face_vectors(self) -> None:
        item = _item("img.jpg")
        item.media_file.__enter__ = lambda s: s
        item.media_file.__exit__ = lambda s, *a: None
        item._stack.enter_context(item.media_file)

        fn = faces_stage(StubInsightFaceModel(faces_per_image=2))[0].fn
        result = fn([item])

        assert len(result) == 1
        assert len(result[0].face_vectors) == 2
        assert len(result[0].face_vectors[0]) == 512

    def test_non_image_yields_empty_face_vectors(self) -> None:
        item = _item("audio.mp3")
        item.media_file.media_type = "audio"
        item.media_file.__enter__ = lambda s: s
        item.media_file.__exit__ = lambda s, *a: None
        item._stack.enter_context(item.media_file)

        fn = faces_stage(StubInsightFaceModel(faces_per_image=2))[0].fn
        result = fn([item])

        assert result[0].face_vectors == []

    def test_empty_input_passthrough(self) -> None:
        assert faces_stage(StubInsightFaceModel())[0].fn([]) == []


# ---------------------------------------------------------------------------
# assign_clusters_stage
# ---------------------------------------------------------------------------


class TestAssignClustersStage:
    def test_assigns_cluster_ids_for_each_face(self) -> None:
        from indexer.face_cluster import FaceClusterer

        face_store = _make_face_store()
        clusterer = FaceClusterer(face_store)

        item = _item("img.jpg")
        item.face_vectors = [[0.1] * 512, [0.9] * 512]

        fn = assign_clusters_stage(clusterer)[0].fn
        result = fn([item])

        assert len(result[0].face_cluster_ids) == 2

    def test_no_faces_yields_empty_cluster_ids(self) -> None:
        from indexer.face_cluster import FaceClusterer

        face_store = _make_face_store()
        clusterer = FaceClusterer(face_store)

        item = _item()
        item.face_vectors = []
        result = assign_clusters_stage(clusterer)[0].fn([item])
        assert result[0].face_cluster_ids == []


# ---------------------------------------------------------------------------
# upsert_captions_stage
# ---------------------------------------------------------------------------


class TestUpsertCaptionsStage:
    def test_stores_face_cluster_ids_in_metadata(self) -> None:
        caption_store = StubIndexStore()
        caption_store.create_empty()

        item = _item("img.jpg")
        item.caption = "a person"
        item.text = "a person"
        item.file_mtime = "1234.0"
        item.exif = {}
        item.face_cluster_ids = ["uuid-1", "uuid-2"]

        upsert_captions_stage(caption_store)[0].fn([item])

        meta = caption_store.get_metadata("img.jpg")
        assert meta is not None
        assert meta["face_cluster_ids"] == "uuid-1,uuid-2"


# ---------------------------------------------------------------------------
# pipeline shape
# ---------------------------------------------------------------------------


class TestPipeline:
    def test_pipeline_has_seven_stages(self) -> None:
        # open, ParallelStage([caption, faces, exif]), drop_failed,
        # assign_clusters, format_text, upsert, close
        pipeline = _indexer().pipeline()
        assert len(pipeline) == 7

    def test_pipeline_stages_are_callable(self) -> None:
        from indexer.pipeline import ParallelStage, Stage

        for step in _indexer().pipeline():
            if isinstance(step, ParallelStage):
                assert all(callable(s.fn) for s in step.stages)
            else:
                assert isinstance(step, Stage)
                assert callable(step.fn)
