"""Integration tests for runner.py — real ChromaDB + real SentenceTransformer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from indexer.pointer import MediaPointer, StorePointer
from indexer.runner import run
from indexer.stores.chroma import ChromaVectorStore
from indexer.vectorizers.sentence_transformer import SentenceTransformerVectorizer
from tests.stubs.caption_model import StubCaptionModel


@pytest.fixture(scope="session", autouse=True)
def _require_vectorizer_model() -> None:
    """Skip the whole module when the sentence-transformer model cannot be loaded."""
    v = SentenceTransformerVectorizer()
    try:
        v.vectorize("warmup")
    except Exception as exc:
        pytest.skip(f"sentence-transformers model unavailable: {exc}")


def _media(path: Path) -> MediaPointer:
    return MediaPointer(scheme="file", remote=None, path=str(path))


def _store(path: Path) -> StorePointer:
    return StorePointer(scheme="file", remote=None, path=str(path))


@pytest.fixture()
def media_dir(tmp_path):
    """A small media directory with real (Pillow-generated) image files."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    media = tmp_path / "media"
    media.mkdir()

    img = Image.new("RGB", (32, 32), color=(255, 0, 0))
    img.save(media / "a.jpg")

    sub = media / "sub"
    sub.mkdir()
    img2 = Image.new("RGB", (16, 16), color=(0, 255, 0))
    img2.save(sub / "c.png")

    return media


@pytest.fixture()
def store_dir(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    return store


class TestRunIntegration:
    def test_creates_db_directory(self, media_dir, store_dir):
        run(
            _media(media_dir),
            _store(store_dir),
            StubCaptionModel(),
            SentenceTransformerVectorizer(),
            ChromaVectorStore(),
        )
        assert (store_dir / "db").is_dir()

    def test_writes_index_meta(self, media_dir, store_dir):
        run(
            _media(media_dir),
            _store(store_dir),
            StubCaptionModel(),
            SentenceTransformerVectorizer(),
            ChromaVectorStore(),
        )
        meta_path = store_dir / "db" / "index_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert "indexed_at" in meta
        assert meta["source"] == f"file://{media_dir}"

    def test_second_run_archives_old_db(self, media_dir, store_dir):
        vectorizer = SentenceTransformerVectorizer()
        run(
            _media(media_dir),
            _store(store_dir),
            StubCaptionModel(),
            vectorizer,
            ChromaVectorStore(),
        )
        run(
            _media(media_dir),
            _store(store_dir),
            StubCaptionModel(),
            vectorizer,
            ChromaVectorStore(),
        )

        # After second run, an archive db_YYYY-MM-DD should exist
        archived = [d for d in store_dir.iterdir() if d.name.startswith("db_")]
        assert len(archived) >= 1
