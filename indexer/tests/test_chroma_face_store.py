"""Tests for ChromaFaceIndexStore — uses real chromadb, in-memory face vectors."""

from __future__ import annotations

from pathlib import Path

import pytest
from common.index import FaceItem

from indexer.stores.chroma_face import ChromaFaceIndexStore


def _vec(seed: float, dim: int = 4) -> list[float]:
    """Return a normalised vector with a simple deterministic pattern."""
    import math

    raw = [seed + i * 0.1 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


class TestCreateEmptyAndAdd:
    def test_create_empty_allows_adding(self) -> None:
        store = ChromaFaceIndexStore()
        store.create_empty()
        store.add(
            "cluster-1",
            FaceItem(embedding=_vec(1.0), cluster_id="cluster-1"),
            {"count": "1", "representative_path": "img.jpg", "image_paths": "img.jpg"},
        )

    def test_add_raises_if_not_initialised(self) -> None:
        store = ChromaFaceIndexStore()
        with pytest.raises(RuntimeError, match="not initialised"):
            store.add("x", FaceItem(embedding=_vec(1.0), cluster_id="x"), {})


class TestUpsert:
    def test_upsert_creates_and_updates(self) -> None:
        store = ChromaFaceIndexStore()
        store.create_empty()
        fid = "c1"
        store.add(
            fid,
            FaceItem(embedding=_vec(1.0), cluster_id=fid),
            {"count": "1", "representative_path": "a.jpg", "image_paths": "a.jpg"},
        )
        store.upsert(
            fid,
            FaceItem(embedding=_vec(1.0), cluster_id=fid),
            {"count": "2", "representative_path": "a.jpg", "image_paths": "a.jpg,b.jpg"},
        )
        meta = store.get_metadata(fid)
        assert meta is not None
        assert meta["count"] == "2"


class TestGetMetadata:
    def test_returns_metadata_for_known_id(self) -> None:
        store = ChromaFaceIndexStore()
        store.create_empty()
        store.add(
            "c1",
            FaceItem(embedding=_vec(1.0), cluster_id="c1"),
            {"count": "1", "representative_path": "a.jpg", "image_paths": "a.jpg"},
        )
        meta = store.get_metadata("c1")
        assert meta is not None
        assert meta["count"] == "1"

    def test_returns_none_for_missing(self) -> None:
        store = ChromaFaceIndexStore()
        store.create_empty()
        assert store.get_metadata("nonexistent") is None


class TestListAll:
    def test_returns_clusters_sorted_by_count(self) -> None:
        store = ChromaFaceIndexStore()
        store.create_empty()
        store.add(
            "c_low",
            FaceItem(embedding=_vec(1.0), cluster_id="c_low"),
            {"count": "1", "representative_path": "a.jpg", "image_paths": "a.jpg"},
        )
        store.add(
            "c_high",
            FaceItem(embedding=_vec(2.0), cluster_id="c_high"),
            {"count": "10", "representative_path": "b.jpg", "image_paths": "b.jpg"},
        )

        results = store.list_all(top_k=10)
        assert len(results) == 2
        assert results[0].id == "c_high"
        assert results[1].id == "c_low"

    def test_empty_store_returns_empty(self) -> None:
        store = ChromaFaceIndexStore()
        store.create_empty()
        assert store.list_all(top_k=10) == []

    def test_top_k_limits_results(self) -> None:
        store = ChromaFaceIndexStore()
        store.create_empty()
        for i in range(5):
            cid = f"c{i}"
            store.add(
                cid,
                FaceItem(embedding=_vec(float(i)), cluster_id=cid),
                {"count": str(i), "representative_path": f"{i}.jpg", "image_paths": f"{i}.jpg"},
            )

        results = store.list_all(top_k=3)
        assert len(results) == 3


class TestSaveAndLoad:
    def test_save_and_reload(self, tmp_path: Path) -> None:
        store = ChromaFaceIndexStore()
        store.create_empty()
        store.add(
            "c1",
            FaceItem(embedding=_vec(1.0), cluster_id="c1"),
            {"count": "2", "representative_path": "img.jpg", "image_paths": "img.jpg"},
        )
        store.save(tmp_path / "db")

        store2 = ChromaFaceIndexStore()
        store2.load(tmp_path / "db")
        meta = store2.get_metadata("c1")
        assert meta is not None
        assert meta["count"] == "2"

    def test_save_raises_if_not_initialised(self) -> None:
        store = ChromaFaceIndexStore()
        with pytest.raises(RuntimeError, match="create_empty"):
            store.save(Path("/tmp/nowhere"))


class TestLoadForUpdate:
    def test_load_for_update_copies_and_allows_modification(self, tmp_path: Path) -> None:
        store = ChromaFaceIndexStore()
        store.create_empty()
        store.add(
            "c1",
            FaceItem(embedding=_vec(1.0), cluster_id="c1"),
            {"count": "1", "representative_path": "a.jpg", "image_paths": "a.jpg"},
        )
        store.save(tmp_path / "db")

        store2 = ChromaFaceIndexStore()
        store2.load_for_update(tmp_path / "db")
        store2.upsert(
            "c1",
            FaceItem(embedding=_vec(1.0), cluster_id="c1"),
            {"count": "5", "representative_path": "a.jpg", "image_paths": "a.jpg"},
        )
        dest2 = tmp_path / "db2"
        store2.save(dest2)

        store3 = ChromaFaceIndexStore()
        store3.load(dest2)
        assert store3.get_metadata("c1") is not None
        assert store3.get_metadata("c1")["count"] == "5"  # type: ignore[index]

    def test_load_for_update_raises_if_faces_dir_missing(self, tmp_path: Path) -> None:
        (tmp_path / "db").mkdir()
        store = ChromaFaceIndexStore()
        with pytest.raises(FileNotFoundError):
            store.load_for_update(tmp_path / "db")


class TestCreatedAt:
    def test_returns_none_when_no_meta_file(self, tmp_path: Path) -> None:
        store = ChromaFaceIndexStore()
        assert store.created_at(tmp_path / "missing") is None


class TestCheckpoint:
    def test_checkpoint_copies_data(self, tmp_path: Path) -> None:
        store = ChromaFaceIndexStore()
        store.create_empty()
        store.add(
            "c1",
            FaceItem(embedding=_vec(1.0), cluster_id="c1"),
            {"count": "1", "representative_path": "a.jpg", "image_paths": "a.jpg"},
        )
        cp_path = tmp_path / "checkpoint"
        store.checkpoint(cp_path)
        assert (cp_path / "faces").exists()

    def test_checkpoint_raises_if_not_initialised(self) -> None:
        store = ChromaFaceIndexStore()
        with pytest.raises(RuntimeError, match="create_empty"):
            store.checkpoint(Path("/tmp/nowhere"))
