"""Tests for ChromaVectorStore — focus on query() edge cases."""

from __future__ import annotations

from unittest.mock import MagicMock

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
