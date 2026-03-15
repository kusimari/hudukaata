"""Tests for startup.load()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from search.config import Settings
from search.startup import AppState, load


def _settings(store_uri: str, top_k: int = 5) -> Settings:
    return Settings(store=store_uri, media="file:///media", top_k=top_k)


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
        # db/ exists but index_meta.json is absent
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
