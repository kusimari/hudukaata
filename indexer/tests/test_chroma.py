"""Tests for ChromaVectorStore — chromadb is mocked throughout."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from indexer.stores.chroma import _META_FILE


@pytest.fixture()
def mock_chromadb():
    """Patch chromadb via sys.modules so the lazy `import chromadb` inside
    load() / create_empty() picks up our mock, not the real library."""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.create_collection.return_value = mock_collection
    mock_client.get_or_create_collection.return_value = mock_collection

    mock_chroma = MagicMock()
    mock_chroma.PersistentClient.return_value = mock_client

    mock_settings_cls = MagicMock(return_value=MagicMock())
    mock_config = MagicMock()
    mock_config.Settings = mock_settings_cls

    with patch.dict(
        "sys.modules",
        {
            "chromadb": mock_chroma,
            "chromadb.config": mock_config,
        },
    ):
        yield mock_chroma, mock_client, mock_collection


class TestCreateEmptyAndAdd:
    def test_create_empty_initialises_collection(self, mock_chromadb):
        from indexer.stores.chroma import ChromaVectorStore

        mock_chroma_mod, mock_client, _ = mock_chromadb
        store = ChromaVectorStore()
        store.create_empty()

        mock_chroma_mod.PersistentClient.assert_called_once()
        mock_client.create_collection.assert_called_once_with("media")

    def test_add_delegates_to_collection(self, mock_chromadb):
        from indexer.stores.chroma import ChromaVectorStore

        _, _, mock_collection = mock_chromadb
        store = ChromaVectorStore()
        store.create_empty()

        store.add("id1", [0.1, 0.2], {"caption": "cat"})

        mock_collection.add.assert_called_once_with(
            ids=["id1"],
            embeddings=[[0.1, 0.2]],
            metadatas=[{"caption": "cat"}],
        )

    def test_add_raises_if_not_initialised(self):
        from indexer.stores.chroma import ChromaVectorStore

        store = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not initialised"):
            store.add("x", [1.0], {})


class TestSave:
    def test_save_moves_tmp_dir_and_writes_metadata(self, mock_chromadb, tmp_path):
        from indexer.stores.chroma import ChromaVectorStore

        store = ChromaVectorStore()
        store.create_empty()

        # Simulate that create_empty created _tmp_dir on disk
        assert store._tmp_dir is not None
        store._tmp_dir.mkdir(parents=True, exist_ok=True)

        dest = tmp_path / "db_new"
        store.save(dest)

        assert dest.is_dir()
        assert store._tmp_dir is None  # cleared after move
        meta = json.loads((dest / _META_FILE).read_text())
        assert "created_at" in meta

    def test_save_raises_if_not_initialised(self):
        from indexer.stores.chroma import ChromaVectorStore

        store = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not initialised"):
            store.save(Path("/tmp/nowhere"))


class TestLoad:
    def test_load_opens_persistent_client(self, mock_chromadb, tmp_path):
        from indexer.stores.chroma import ChromaVectorStore

        mock_chroma_mod, mock_client, _ = mock_chromadb
        store = ChromaVectorStore()
        store.load(tmp_path / "db")

        mock_chroma_mod.PersistentClient.assert_called_once()
        mock_client.get_or_create_collection.assert_called_once_with("media")


class TestCreatedAt:
    def test_returns_datetime_from_sidecar(self, tmp_path):
        from indexer.stores.chroma import ChromaVectorStore

        db_dir = tmp_path / "db"
        db_dir.mkdir()
        ts = "2024-06-15T12:00:00+00:00"
        (db_dir / _META_FILE).write_text(json.dumps({"created_at": ts}))

        store = ChromaVectorStore()
        result = store.created_at(db_dir)

        assert result == datetime.fromisoformat(ts)

    def test_returns_none_when_no_sidecar(self, tmp_path):
        from indexer.stores.chroma import ChromaVectorStore

        store = ChromaVectorStore()
        assert store.created_at(tmp_path / "missing") is None

    def test_returns_none_on_corrupt_sidecar(self, tmp_path):
        from indexer.stores.chroma import ChromaVectorStore

        db_dir = tmp_path / "db"
        db_dir.mkdir()
        (db_dir / _META_FILE).write_text("not json")

        store = ChromaVectorStore()
        assert store.created_at(db_dir) is None
