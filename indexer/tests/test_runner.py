"""Tests for runner.py — full run using stubs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from indexer.pointer import MediaPointer
from indexer.runner import run
from tests.stubs.caption_model import StubCaptionModel
from tests.stubs.vector_store import StubVectorStore
from tests.stubs.vectorizer import StubVectorizer


def _file_pointer(path: Path) -> MediaPointer:
    return MediaPointer(scheme="file", remote=None, path=str(path))


@pytest.fixture()
def media_dir(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "a.jpg").write_bytes(b"fake jpeg")
    (media / "b.mp3").write_bytes(b"fake mp3")
    (media / "sub").mkdir()
    (media / "sub" / "c.png").write_bytes(b"fake png")
    return media


@pytest.fixture()
def store_dir(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    return store


class TestRun:
    def test_all_files_indexed(self, media_dir, store_dir):
        vector_store = StubVectorStore()

        run(
            media=_file_pointer(media_dir),
            store=_file_pointer(store_dir),
            caption_model=StubCaptionModel(),
            vectorizer=StubVectorizer(),
            vector_store=vector_store,
        )

        assert len(vector_store.docs) == 3
        keys = set(vector_store.docs.keys())
        assert any("a.jpg" in k for k in keys)
        assert any("b.mp3" in k for k in keys)
        assert any("c.png" in k for k in keys)

    def test_metadata_contains_caption(self, media_dir, store_dir):
        vector_store = StubVectorStore()

        run(
            media=_file_pointer(media_dir),
            store=_file_pointer(store_dir),
            caption_model=StubCaptionModel(),
            vectorizer=StubVectorizer(),
            vector_store=vector_store,
        )

        for doc_id, (vector, metadata) in vector_store.docs.items():
            assert "caption" in metadata
            assert metadata["caption"] == doc_id  # StubCaptionModel returns path

    def test_db_new_is_promoted_to_db(self, media_dir, store_dir):
        run(
            media=_file_pointer(media_dir),
            store=_file_pointer(store_dir),
            caption_model=StubCaptionModel(),
            vectorizer=StubVectorizer(),
            vector_store=StubVectorStore(),
        )

        assert (store_dir / "db").is_dir()
        assert not (store_dir / "db_new").exists()

    def test_stale_db_new_cleaned_before_run(self, media_dir, store_dir):
        # Leave a stale db_new from a previous run
        (store_dir / "db_new").mkdir()
        (store_dir / "db_new" / "stale.txt").write_text("stale")

        run(
            media=_file_pointer(media_dir),
            store=_file_pointer(store_dir),
            caption_model=StubCaptionModel(),
            vectorizer=StubVectorizer(),
            vector_store=StubVectorStore(),
        )

        assert (store_dir / "db").is_dir()
        # Stale dir was cleaned up
        assert not (store_dir / "db_new").exists()
