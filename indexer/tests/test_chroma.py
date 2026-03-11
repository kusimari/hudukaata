"""Tests for ChromaVectorStore — uses real chromadb (no mocking)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from common.stores.chroma import _META_FILE, ChromaVectorStore
from common.vectorizers.sentence_transformer import SentenceTransformerVectorizer


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
        with pytest.raises(RuntimeError, match="create_empty"):
            store.save(Path("/tmp/nowhere"))

    def test_save_tmp_dir_cleared(self, tmp_path):
        store = ChromaVectorStore()
        store.create_empty()
        store.save(tmp_path / "db")
        assert store._tmp_dir is None


class TestLoad:
    def test_load_opens_existing_collection(self, tmp_path):
        store = ChromaVectorStore()
        store.create_empty()
        store.add("x", [1.0, 2.0], {"caption": "hi"})
        dest = tmp_path / "db"
        store.save(dest)

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


class TestQuery:
    def test_query_raises_if_not_initialised(self):
        store = ChromaVectorStore()
        with pytest.raises(RuntimeError, match="not initialised"):
            store.query([0.1, 0.2], n_results=3)

    def test_query_returns_list_of_dicts(self, tmp_path):
        store = ChromaVectorStore()
        store.create_empty()
        store.add("img_0.jpg", [1.0, 0.0], {"caption": "a dog"})
        store.add("img_1.jpg", [0.0, 1.0], {"caption": "a cat"})

        results = store.query([1.0, 0.0], n_results=1)
        assert len(results) == 1
        assert "id" in results[0]
        assert "caption" in results[0]

    def test_semantic_search_finds_relevant_results(self, tmp_path):
        """Add 100 items via real sentence-transformer vectors and verify semantic
        search surfaces the thematically-closest documents at the top."""
        vectorizer = SentenceTransformerVectorizer()
        try:
            vectorizer.vectorize("warmup")  # force download / cache load
        except Exception as exc:
            pytest.skip(f"sentence-transformers model unavailable: {exc}")
        store = ChromaVectorStore()
        store.create_empty()

        # 98 generic captions + 2 topical ones we expect to find
        captions = [f"A photo of random object number {i}" for i in range(98)]
        captions.append("A dog playing fetch in the park with a ball")  # idx 98
        captions.append("A cat sitting on a warm windowsill in the sun")  # idx 99

        for i, caption in enumerate(captions):
            vec = vectorizer.vectorize(caption)
            store.add(
                f"img_{i:03d}.jpg",
                vec,
                {"caption": caption, "relative_path": f"img_{i:03d}.jpg"},
            )

        # Query is semantically close to the dog caption
        query_vec = vectorizer.vectorize("dog fetching a ball outdoors")
        results = store.query(query_vec, n_results=5)

        assert len(results) > 0
        assert all("id" in r and "caption" in r for r in results)

        found_captions = [r["caption"] for r in results]
        assert any("dog" in c.lower() for c in found_captions), (
            f"Expected dog-related caption in top-5 results, got: {found_captions}"
        )
