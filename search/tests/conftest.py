"""Shared fixtures for search tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from common.meta import INDEX_META_FILE
from common.pointer import StorePointer

from search.startup import AppState
from tests.stubs.vector_store import StubVectorStore
from tests.stubs.vectorizer import StubVectorizer


@pytest.fixture()
def stub_state() -> AppState:
    """An :class:`AppState` backed entirely by stubs — no disk, no models."""
    return AppState(
        vectorizer=StubVectorizer(),
        vector_store=StubVectorStore(),
        top_k=5,
        media_ptr=StorePointer.parse("file:///media"),
    )


@pytest.fixture()
def index_db(tmp_path: Path) -> Path:
    """A minimal on-disk index DB directory containing index_meta.json."""
    db = tmp_path / "store" / "db"
    db.mkdir(parents=True)
    meta = {
        "indexed_at": datetime.now(UTC).isoformat(),
        "source": "file:///media",
        "vectorizer": "sentence-transformer",
        "vector_store": "chroma",
    }
    (db / INDEX_META_FILE).write_text(json.dumps(meta))
    return tmp_path / "store"
