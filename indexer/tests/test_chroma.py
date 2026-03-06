"""Tests for ChromaVectorStore — uses real chromadb (no mocking)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from indexer.stores.chroma import _META_FILE, ChromaVectorStore


class TestCreateEmptyAndAdd:
    def test_create_empty_allows_adding(self, tmp_path):
        store = ChromaVectorStore()
        store.create_empty()
        # Should not raise
        store.add("id1", [0.1, 0.2, 0.3], {"caption": "a cat"})

    def test_add_raises_if_not_initialised(self):
        store = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not initialised"):
            store.add("x", [1.0], {})

    def test_multiple_adds(self, tmp_path):
        store = ChromaVectorStore()
        store.create_empty()
        store.add("doc1", [0.1] * 8, {"caption": "first"})
        store.add("doc2", [0.2] * 8, {"caption": "second"})
        # If no exception, both were accepted
        dest = tmp_path / "db"
        store.save(dest)
        assert dest.is_dir()


class TestSave:
    def test_save_creates_directory_and_metadata(self, tmp_path):
        store = ChromaVectorStore()
        store.create_empty()
        store.add("id1", [0.5] * 4, {"caption": "test"})

        dest = tmp_path / "db_new"
        store.save(dest)

        assert dest.is_dir()
        assert (dest / _META_FILE).exists()
        meta = json.loads((dest / _META_FILE).read_text())
        assert "created_at" in meta

    def test_save_raises_if_not_initialised(self):
        store = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not initialised"):
            store.save(Path("/tmp/nowhere"))

    def test_save_tmp_dir_cleared(self, tmp_path):
        store = ChromaVectorStore()
        store.create_empty()
        store.save(tmp_path / "db")
        assert store._tmp_dir is None


class TestLoad:
    def test_load_opens_existing_collection(self, tmp_path):
        # Create + save
        store = ChromaVectorStore()
        store.create_empty()
        store.add("x", [1.0, 2.0], {"caption": "hi"})
        dest = tmp_path / "db"
        store.save(dest)

        # Load into a fresh instance
        store2 = ChromaVectorStore()
        store2.load(dest)
        # Should not raise — collection exists
        store2.add("y", [3.0, 4.0], {"caption": "there"})


class TestCreatedAt:
    def test_returns_datetime_from_sidecar(self, tmp_path):
        db_dir = tmp_path / "db"
        db_dir.mkdir()
        ts = "2024-06-15T12:00:00+00:00"
        (db_dir / _META_FILE).write_text(json.dumps({"created_at": ts}))

        store = ChromaVectorStore()
        result = store.created_at(db_dir)

        assert result == datetime.fromisoformat(ts)

    def test_returns_none_when_no_sidecar(self, tmp_path):
        store = ChromaVectorStore()
        assert store.created_at(tmp_path / "missing") is None

    def test_returns_none_on_corrupt_sidecar(self, tmp_path):
        db_dir = tmp_path / "db"
        db_dir.mkdir()
        (db_dir / _META_FILE).write_text("not json")

        store = ChromaVectorStore()
        assert store.created_at(db_dir) is None

    def test_roundtrip_created_at_after_save(self, tmp_path):
        store = ChromaVectorStore()
        store.create_empty()
        dest = tmp_path / "db"
        store.save(dest)

        result = store.created_at(dest)
        assert isinstance(result, datetime)
