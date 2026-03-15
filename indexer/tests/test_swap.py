"""Tests for swap.py."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from common.base import StorePointer

from indexer.swap import cleanup_stale_tmp, commit, prepare_temp_dir


def _store(path: Path) -> StorePointer:
    return StorePointer(scheme="file", remote=None, path=str(path))


class TestPrepTempDir:
    def test_creates_dir(self, tmp_path):
        local_tmp = tmp_path / "work"
        prepare_temp_dir(_store(tmp_path), local_tmp)
        assert local_tmp.is_dir()


class TestCleanupStaleTmp:
    def test_removes_db_new(self, tmp_path):
        (tmp_path / "db_new").mkdir()
        cleanup_stale_tmp(_store(tmp_path))
        assert not (tmp_path / "db_new").exists()

    def test_removes_db_checkpoint(self, tmp_path):
        (tmp_path / "db_checkpoint").mkdir()
        cleanup_stale_tmp(_store(tmp_path))
        assert not (tmp_path / "db_checkpoint").exists()

    def test_removes_both_stale_dirs(self, tmp_path):
        (tmp_path / "db_new").mkdir()
        (tmp_path / "db_checkpoint").mkdir()
        cleanup_stale_tmp(_store(tmp_path))
        assert not (tmp_path / "db_new").exists()
        assert not (tmp_path / "db_checkpoint").exists()

    def test_noop_when_no_stale_dir(self, tmp_path):
        cleanup_stale_tmp(_store(tmp_path))  # should not raise


class TestCommit:
    def test_promotes_db_new_to_db(self, tmp_path):
        store_root = tmp_path / "store"
        store_root.mkdir()
        (store_root / "db_new").mkdir()
        (store_root / "db_new" / "data.txt").write_text("x")

        local_tmp = tmp_path / "local"
        local_tmp.mkdir()

        commit(_store(store_root), local_tmp, created_at=None)

        assert (store_root / "db").is_dir()
        assert not (store_root / "db_new").exists()

    def test_archives_old_db(self, tmp_path):
        store_root = tmp_path / "store"
        store_root.mkdir()
        (store_root / "db").mkdir()
        (store_root / "db" / "old.txt").write_text("old")
        (store_root / "db_new").mkdir()
        (store_root / "db_new" / "new.txt").write_text("new")

        ts = datetime(2024, 6, 15, tzinfo=UTC)
        local_tmp = tmp_path / "local"
        local_tmp.mkdir()

        commit(_store(store_root), local_tmp, created_at=ts)

        assert (store_root / "db").is_dir()
        assert (store_root / "db_2024-06-15").is_dir()
        assert not (store_root / "db_new").exists()
