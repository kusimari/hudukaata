"""Tests for ChromaVectorStore — query() edge cases + new update methods."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from common.stores.chroma import ChromaVectorStore


def _make_store(count: int, query_result: dict) -> ChromaVectorStore:  # type: ignore[type-arg]
    """Return a ChromaVectorStore whose internal collection is a MagicMock."""
    store = ChromaVectorStore()
    mock_col = MagicMock()
    mock_col.count.return_value = count
    mock_col.query.return_value = query_result
    store._collection = mock_col
    return store


class TestQueryClamp:
    """ChromaVectorStore.query() must clamp n_results to collection size."""

    def test_returns_empty_list_when_collection_is_empty(self) -> None:
        store = _make_store(count=0, query_result={})
        result = store.query(vector=[0.1, 0.2], n_results=5)
        assert result == []
        store._collection.query.assert_not_called()

    def test_clamps_n_results_to_collection_count(self) -> None:
        query_result = {
            "ids": [["id1", "id2"]],
            "metadatas": [
                [
                    {"caption": "blue sky", "relative_path": "a.png"},
                    {"caption": "green field", "relative_path": "b.png"},
                ]
            ],
        }
        store = _make_store(count=2, query_result=query_result)
        result = store.query(vector=[0.1, 0.2], n_results=5)
        # Should pass effective_n=2 (clamped from 5) to ChromaDB.
        store._collection.query.assert_called_once_with(
            query_embeddings=[[0.1, 0.2]],
            n_results=2,
            include=["metadatas"],
        )
        assert len(result) == 2
        assert result[0]["id"] == "id1"
        assert result[1]["relative_path"] == "b.png"

    def test_passes_n_results_unchanged_when_below_count(self) -> None:
        query_result = {
            "ids": [["id1"]],
            "metadatas": [[{"caption": "c", "relative_path": "c.png"}]],
        }
        store = _make_store(count=10, query_result=query_result)
        store.query(vector=[0.5], n_results=1)
        store._collection.query.assert_called_once_with(
            query_embeddings=[[0.5]],
            n_results=1,
            include=["metadatas"],
        )

    def test_raises_when_not_initialised(self) -> None:
        store = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not initialised"):
            store.query(vector=[0.1], n_results=1)


class TestUpsert:
    def _store_with_collection(self) -> tuple[ChromaVectorStore, MagicMock]:
        store = ChromaVectorStore()
        store._tmp_dir = MagicMock()  # type: ignore[assignment]
        mock_col = MagicMock()
        store._collection = mock_col
        return store, mock_col

    def test_upsert_calls_collection_upsert(self) -> None:
        store, mock_col = self._store_with_collection()
        store.upsert("id1", [0.1, 0.2], {"caption": "sky"})
        mock_col.upsert.assert_called_once_with(
            ids=["id1"],
            embeddings=[[0.1, 0.2]],
            metadatas=[{"caption": "sky"}],
        )

    def test_upsert_updates_cache_if_primed(self) -> None:
        store, mock_col = self._store_with_collection()
        # Prime the cache manually.
        store._meta_cache = {"old": {"caption": "old"}}
        store.upsert("new_id", [0.5], {"caption": "new"})
        assert store._meta_cache["new_id"] == {"caption": "new"}

    def test_upsert_raises_when_not_initialised(self) -> None:
        store = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not initialised"):
            store.upsert("x", [0.1], {})


class TestGetMetadata:
    def _store_with_docs(self, docs: dict[str, dict[str, str]]) -> ChromaVectorStore:
        store = ChromaVectorStore()
        mock_col = MagicMock()
        ids = list(docs.keys())
        metadatas = [docs[i] for i in ids]
        mock_col.get.return_value = {"ids": ids, "metadatas": metadatas}
        store._collection = mock_col
        return store

    def test_returns_none_for_missing_id(self) -> None:
        store = self._store_with_docs({})
        assert store.get_metadata("nonexistent") is None

    def test_returns_correct_metadata(self) -> None:
        store = self._store_with_docs({"img.jpg": {"caption": "a cat"}})
        result = store.get_metadata("img.jpg")
        assert result == {"caption": "a cat"}

    def test_cache_primed_on_first_call_only(self) -> None:
        store = self._store_with_docs({"x.png": {"caption": "x"}})
        # Two calls — collection.get() must be invoked exactly once.
        store.get_metadata("x.png")
        store.get_metadata("x.png")
        assert store._collection.get.call_count == 1

    def test_raises_when_not_initialised(self) -> None:
        store = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not initialised"):
            store.get_metadata("x")


class TestCheckpoint:
    def test_checkpoint_copies_tmp_dir(self, tmp_path: MagicMock) -> None:
        store = ChromaVectorStore()
        src = MagicMock(spec=["__str__", "exists"])
        store._tmp_dir = src  # type: ignore[assignment]
        dest = tmp_path / "ckpt"
        with patch("common.stores.chroma.shutil.copytree") as mock_copy:
            store.checkpoint(dest)
        mock_copy.assert_called_once_with(str(src), str(dest))

    def test_checkpoint_removes_existing_dest(self, tmp_path: MagicMock) -> None:
        store = ChromaVectorStore()
        store._tmp_dir = MagicMock()  # type: ignore[assignment]
        dest = tmp_path / "ckpt"
        dest.mkdir()
        with (
            patch("common.stores.chroma.shutil.copytree"),
            patch("common.stores.chroma.shutil.rmtree") as mock_rm,
        ):
            store.checkpoint(dest)
        mock_rm.assert_called_once_with(dest)

    def test_checkpoint_raises_when_not_initialised(self, tmp_path: MagicMock) -> None:
        store = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="checkpoint"):
            store.checkpoint(tmp_path / "ckpt")


class TestSavePreservesCreatedAt:
    def test_save_uses_created_at_when_set(self, tmp_path: MagicMock) -> None:
        from datetime import UTC, datetime

        store = ChromaVectorStore()
        fixed_ts = datetime(2024, 1, 15, tzinfo=UTC)
        store._created_at = fixed_ts
        fake_tmp = tmp_path / "fake_tmp"
        fake_tmp.mkdir()
        store._tmp_dir = fake_tmp
        store._client = None
        store._collection = None
        dest = tmp_path / "db_out"
        store.save(dest)
        import json

        from common.stores.chroma import _META_FILE

        data = json.loads((dest / _META_FILE).read_text())
        assert data["created_at"] == fixed_ts.isoformat()
