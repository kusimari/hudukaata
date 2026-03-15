"""Shared fixtures for search tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from common.base import INDEX_META_FILE
from common.media import FileMediaSource

from search.startup import AppState
from tests.stubs.index_store import StubIndexStore


@pytest.fixture()
def stub_state() -> AppState:
    """An :class:`AppState` backed entirely by stubs — no disk, no models."""
    return AppState(
        index_store=StubIndexStore(),
        top_k=5,
        media_src=FileMediaSource(path="/media"),
    )


@pytest.fixture()
def index_db(tmp_path: Path) -> Path:
    """A minimal on-disk index DB directory containing index_meta.json."""
    db = tmp_path / "store" / "db"
    db.mkdir(parents=True)
    meta = {
        "indexed_at": datetime.now(UTC).isoformat(),
        "source": "file:///media",
        "index_store": "indexer.stores.chroma_caption.ChromaCaptionIndexStore",
    }
    (db / INDEX_META_FILE).write_text(json.dumps(meta))
    return tmp_path / "store"
