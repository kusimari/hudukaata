"""Tests for startup.load()."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from search.config import Settings
from search.startup import _SERVE_REGISTRY, AppState, available_indexer_keys, load


def _settings(store_uri: str, top_k: int = 5, indexer_key: str = "blip2-sentok-exif") -> Settings:
    return Settings(store=store_uri, media="file:///media", top_k=top_k, indexer_key=indexer_key)


def _write_meta(db: Path, *, face_store: str | None = None) -> None:
    meta = {
        "indexed_at": datetime.now(UTC).isoformat(),
        "source": "file:///media",
        "index_store": "indexer.stores.chroma_caption.ChromaCaptionIndexStore",
        "indexer_version": "3.0.0",
    }
    if face_store is not None:
        meta["face_store"] = face_store
    from common.base import INDEX_META_FILE

    (db / INDEX_META_FILE).write_text(json.dumps(meta))


class TestRegistry:
    def test_available_indexer_keys_returns_expected(self) -> None:
        keys = available_indexer_keys()
        assert "blip2-sentok-exif" in keys
        assert "blip2-sentok-exif-insightface" in keys

    def test_registry_entries_have_required_keys(self) -> None:
        for key, entry in _SERVE_REGISTRY.items():
            assert "caption_store" in entry, f"{key} missing caption_store"
            assert "face_store" in entry, f"{key} missing face_store"


class TestLoad:
    def test_raises_when_no_db_dir(self, tmp_path: Path) -> None:
        store = tmp_path / "empty_store"
        store.mkdir()
        with pytest.raises(RuntimeError, match="No 'db' directory"):
            load(_settings(f"file://{store}"))

    def test_raises_when_index_meta_missing(self, tmp_path: Path) -> None:
        """db/ exists but has no index_meta.json — should propagate FileNotFoundError."""
        store = tmp_path / "store"
        (store / "db").mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            load(_settings(f"file://{store}"))

    def test_returns_app_state(self, index_db: Path) -> None:
        """load() with a valid store returns AppState with the right top_k."""
        stub_idx = MagicMock()

        with patch("search.startup.resolve_index_store", return_value=stub_idx):
            state = load(_settings(f"file://{index_db}", top_k=3))

        assert isinstance(state, AppState)
        assert state.top_k == 3
        assert state.index_store is stub_idx

    def test_index_store_load_called_with_db_path(self, index_db: Path) -> None:
        """The index store's load() must be called with the local db path."""
        stub_idx = MagicMock()

        with patch("search.startup.resolve_index_store", return_value=stub_idx):
            load(_settings(f"file://{index_db}"))

        stub_idx.load.assert_called_once()
        called_path: Path = stub_idx.load.call_args[0][0]
        assert called_path.name == "db"

    def test_file_scheme_db_tmp_path_is_none(self, index_db: Path) -> None:
        """For file:// sources, no temp dir cleanup is needed."""
        stub_idx = MagicMock()

        with patch("search.startup.resolve_index_store", return_value=stub_idx):
            state = load(_settings(f"file://{index_db}"))

        assert state._db_tmp_path is None

    def test_raises_unknown_indexer_key(self, index_db: Path) -> None:
        with pytest.raises(RuntimeError, match="Unknown indexer key"):
            load(_settings(f"file://{index_db}", indexer_key="nonexistent-key"))

    def test_face_store_none_for_caption_only_indexer(self, index_db: Path) -> None:
        stub_idx = MagicMock()
        with patch("search.startup.resolve_index_store", return_value=stub_idx):
            state = load(_settings(f"file://{index_db}", indexer_key="blip2-sentok-exif"))
        assert state.face_store is None

    def test_raises_when_face_store_required_but_meta_missing(self, tmp_path: Path) -> None:
        """Serving with insightface key but no face_store in meta → RuntimeError."""
        store = tmp_path / "store"
        db = store / "db"
        db.mkdir(parents=True)
        _write_meta(db)  # no face_store in meta

        with pytest.raises(RuntimeError, match="requires a face store"):
            load(_settings(f"file://{store}", indexer_key="blip2-sentok-exif-insightface"))

    def test_loads_both_stores_when_face_store_present(self, tmp_path: Path) -> None:
        """When meta has face_store, both caption and face stores are loaded."""
        store = tmp_path / "store"
        db = store / "db"
        db.mkdir(parents=True)
        _write_meta(db, face_store="indexer.stores.chroma_face.ChromaFaceIndexStore")

        stub_caption = MagicMock()
        stub_face = MagicMock()
        call_count = [0]

        def _resolve(name: str) -> MagicMock:
            call_count[0] += 1
            return stub_caption if "caption" in name else stub_face

        with patch("search.startup.resolve_index_store", side_effect=_resolve):
            state = load(_settings(f"file://{store}", indexer_key="blip2-sentok-exif-insightface"))

        assert call_count[0] == 2
        assert state.index_store is stub_caption
        assert state.face_store is stub_face
