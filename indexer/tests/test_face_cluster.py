"""Tests for FaceClusterer — incremental centroid-based face clustering."""

from __future__ import annotations

import math

import pytest

from indexer.face_cluster import FaceClusterer, _cosine_sim
from indexer.stores.chroma_face import ChromaFaceIndexStore

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _unit(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def _make_face_store() -> ChromaFaceIndexStore:
    store = ChromaFaceIndexStore()
    store.create_empty()
    return store


# ---------------------------------------------------------------------------
# _cosine_sim
# ---------------------------------------------------------------------------


class TestCosineSim:
    def test_identical_vectors(self) -> None:
        v = [1.0, 0.0, 0.0]
        assert _cosine_sim(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        assert _cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        assert _cosine_sim([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self) -> None:
        assert _cosine_sim([0.0, 0.0], [1.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# FaceClusterer
# ---------------------------------------------------------------------------


class TestFaceClusterer:
    def test_first_face_creates_cluster(self) -> None:
        store = _make_face_store()
        clusterer = FaceClusterer(store, threshold=0.6)
        cid = clusterer.assign([1.0, 0.0, 0.0], "img1.jpg")
        assert cid is not None
        assert store.get_metadata(cid) is not None

    def test_similar_face_merges_into_same_cluster(self) -> None:
        store = _make_face_store()
        clusterer = FaceClusterer(store, threshold=0.6)

        v1 = _unit([1.0, 0.1, 0.0])
        v2 = _unit([1.0, 0.05, 0.0])  # very similar to v1

        cid1 = clusterer.assign(v1, "img1.jpg")
        cid2 = clusterer.assign(v2, "img2.jpg")

        assert cid1 == cid2

    def test_dissimilar_face_creates_new_cluster(self) -> None:
        store = _make_face_store()
        clusterer = FaceClusterer(store, threshold=0.6)

        v1 = _unit([1.0, 0.0, 0.0])
        v2 = _unit([0.0, 1.0, 0.0])  # orthogonal → very dissimilar

        cid1 = clusterer.assign(v1, "img1.jpg")
        cid2 = clusterer.assign(v2, "img2.jpg")

        assert cid1 != cid2

    def test_cluster_count_increments_on_merge(self) -> None:
        store = _make_face_store()
        clusterer = FaceClusterer(store, threshold=0.6)

        v = _unit([1.0, 0.0])
        cid = clusterer.assign(v, "img1.jpg")
        clusterer.assign(v, "img2.jpg")

        meta = store.get_metadata(cid)
        assert meta is not None
        assert int(meta["count"]) == 2

    def test_image_paths_recorded_in_metadata(self) -> None:
        store = _make_face_store()
        clusterer = FaceClusterer(store, threshold=0.6)

        v = _unit([1.0, 0.0])
        cid = clusterer.assign(v, "img1.jpg")
        clusterer.assign(v, "img2.jpg")

        meta = store.get_metadata(cid)
        assert meta is not None
        paths = meta["image_paths"].split(",")
        assert "img1.jpg" in paths
        assert "img2.jpg" in paths

    def test_same_image_not_duplicated_in_paths(self) -> None:
        store = _make_face_store()
        clusterer = FaceClusterer(store, threshold=0.6)

        v = _unit([1.0, 0.0])
        cid = clusterer.assign(v, "img1.jpg")
        clusterer.assign(v, "img1.jpg")  # same image again

        meta = store.get_metadata(cid)
        assert meta is not None
        paths = [p for p in meta["image_paths"].split(",") if p]
        assert paths.count("img1.jpg") == 1

    def test_loads_existing_clusters_on_new_clusterer(self) -> None:
        """A new FaceClusterer using the same store should pick up existing clusters."""
        store = _make_face_store()
        clusterer1 = FaceClusterer(store, threshold=0.6)

        v = _unit([1.0, 0.0, 0.0])
        cid1 = clusterer1.assign(v, "img1.jpg")

        # New clusterer on the same store — should merge with existing cluster.
        clusterer2 = FaceClusterer(store, threshold=0.6)
        v2 = _unit([1.0, 0.05, 0.0])
        cid2 = clusterer2.assign(v2, "img2.jpg")

        assert cid1 == cid2
