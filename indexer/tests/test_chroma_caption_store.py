"""Tests for ChromaCaptionIndexStore — uses real chromadb, stub vectorizer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from common.index import CaptionItem

from indexer.stores.chroma_caption import _META_FILE, ChromaCaptionIndexStore
from indexer.vectorizers.base import Vectorizer
from tests.stubs.index_store import StubIndexStore

_DIM = 4


class _FixedVectorizer(Vectorizer):
    """Returns a fixed vector of length _DIM for any input."""

    def vectorize(self, text: str) -> list[float]:
        return [0.1] * _DIM

    @property
    def dimension(self) -> int:
        return _DIM


class TestCreateEmptyAndAdd:
    def test_create_empty_allows_adding(self) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store.create_empty()
        store.add("id1", CaptionItem(text="a cat"), {"caption": "a cat"})

    def test_add_raises_if_not_initialised(self) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        with pytest.raises(RuntimeError, match="not initialised"):
            store.add("x", CaptionItem(text="text"), {})

    def test_multiple_adds(self, tmp_path: Path) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store.create_empty()
        store.add("doc1", CaptionItem(text="first text"), {"caption": "first"})
        store.add("doc2", CaptionItem(text="second text"), {"caption": "second"})
        dest = tmp_path / "db"
        store.save(dest)
        assert dest.is_dir()


class TestSave:
    def test_save_creates_directory_and_metadata(self, tmp_path: Path) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store.create_empty()
        store.add("id1", CaptionItem(text="test text"), {"caption": "test"})

        dest = tmp_path / "db_new"
        store.save(dest)

        assert dest.is_dir()
        assert (dest / _META_FILE).exists()
        meta = json.loads((dest / _META_FILE).read_text())
        assert "created_at" in meta

    def test_save_raises_if_not_initialised(self) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        with pytest.raises(RuntimeError, match="create_empty"):
            store.save(Path("/tmp/nowhere"))

    def test_save_tmp_dir_cleared(self, tmp_path: Path) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store.create_empty()
        store.save(tmp_path / "db")
        assert store._tmp_dir is None


class TestLoad:
    def test_load_opens_existing_collection(self, tmp_path: Path) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store.create_empty()
        store.add("x", CaptionItem(text="hi there"), {"caption": "hi"})
        dest = tmp_path / "db"
        store.save(dest)

        store2 = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store2.load(dest)
        # Should not raise — collection exists
        store2.add("y", CaptionItem(text="hello there"), {"caption": "there"})


class TestCreatedAt:
    def test_returns_datetime_from_sidecar(self, tmp_path: Path) -> None:
        db_dir = tmp_path / "db"
        db_dir.mkdir()
        ts = "2024-06-15T12:00:00+00:00"
        (db_dir / _META_FILE).write_text(json.dumps({"created_at": ts}))

        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        result = store.created_at(db_dir)

        assert result == datetime.fromisoformat(ts)

    def test_returns_none_when_no_sidecar(self, tmp_path: Path) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        assert store.created_at(tmp_path / "missing") is None

    def test_returns_none_on_corrupt_sidecar(self, tmp_path: Path) -> None:
        db_dir = tmp_path / "db"
        db_dir.mkdir()
        (db_dir / _META_FILE).write_text("not json")

        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        assert store.created_at(db_dir) is None

    def test_roundtrip_created_at_after_save(self, tmp_path: Path) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store.create_empty()
        dest = tmp_path / "db"
        store.save(dest)

        result = store.created_at(dest)
        assert isinstance(result, datetime)


class TestSearch:
    def test_search_raises_if_not_initialised(self) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        with pytest.raises(RuntimeError, match="not initialised"):
            store.search(CaptionItem(text="query"), top_k=3)

    def test_search_returns_index_results(self) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store.create_empty()
        store.add(
            "img_0.jpg",
            CaptionItem(text="a dog"),
            {"caption": "a dog", "relative_path": "img_0.jpg"},
        )
        store.add(
            "img_1.jpg",
            CaptionItem(text="a cat"),
            {"caption": "a cat", "relative_path": "img_1.jpg"},
        )

        results = store.search(CaptionItem(text="animal"), top_k=1)
        assert len(results) == 1
        assert results[0].id in ("img_0.jpg", "img_1.jpg")
        assert results[0].item.text in ("a dog", "a cat")

    def test_search_empty_store_returns_empty(self) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store.create_empty()
        results = store.search(CaptionItem(text="query"), top_k=5)
        assert results == []

    def test_semantic_search_finds_relevant_results(self) -> None:
        """Add 100 items via real sentence-transformer vectors and verify semantic
        search surfaces the thematically-closest documents at the top."""
        from indexer.vectorizers.sentence_transformer import SentenceTransformerVectorizer

        v = SentenceTransformerVectorizer()
        try:
            v.vectorize("warmup")
        except Exception as exc:
            pytest.skip(f"sentence-transformers model unavailable: {exc}")

        store = ChromaCaptionIndexStore(vectorizer=v)
        store.create_empty()

        captions = [f"A photo of random object number {i}" for i in range(98)]
        captions.append("A dog playing fetch in the park with a ball")
        captions.append("A cat sitting on a warm windowsill in the sun")

        for i, caption in enumerate(captions):
            store.add(
                f"img_{i:03d}.jpg",
                CaptionItem(text=caption),
                {"caption": caption, "relative_path": f"img_{i:03d}.jpg"},
            )

        results = store.search(CaptionItem(text="dog fetching a ball outdoors"), top_k=5)

        assert len(results) > 0
        found_captions = [r.item.text for r in results]
        assert any("dog" in c.lower() for c in found_captions), (
            f"Expected dog-related caption in top-5 results, got: {found_captions}"
        )


class TestGetMetadata:
    def test_get_metadata_returns_dict(self) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store.create_empty()
        store.add("x", CaptionItem(text="hello"), {"caption": "hello", "relative_path": "x.jpg"})
        meta = store.get_metadata("x")
        assert meta is not None
        assert meta["caption"] == "hello"

    def test_get_metadata_returns_none_for_missing(self) -> None:
        store = ChromaCaptionIndexStore(vectorizer=_FixedVectorizer())
        store.create_empty()
        assert store.get_metadata("nonexistent") is None


class TestStubIndexStore:
    """Quick sanity tests for the StubIndexStore used in runner tests."""

    def test_upsert_and_get_metadata(self) -> None:
        stub = StubIndexStore()
        stub.create_empty()
        stub.upsert("a", CaptionItem(text="text"), {"k": "v"})
        assert stub.get_metadata("a") == {"k": "v"}

    def test_search_returns_results(self) -> None:
        stub = StubIndexStore()
        stub.create_empty()
        stub.upsert("a", CaptionItem(text="text"), {"caption": "hello", "relative_path": "a.jpg"})
        results = stub.search(CaptionItem(text="anything"), top_k=5)
        assert len(results) == 1
        assert results[0].id == "a"
