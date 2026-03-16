"""Tests for IndexingRunner — orchestration (scan, skip, checkpoint, commit)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from common.base import INDEXER_VERSION, IndexMeta, StorePointer
from common.media import FileMediaSource

from indexer.pipeline import AdaptiveBatchRunner, BatchItem, OneByOneRunner, Stage
from indexer.runner import IndexingRunner
from tests.stubs.index_store import StubIndexStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _passthrough(items: list[BatchItem]) -> list[BatchItem]:
    return items


def _noop_pipeline() -> list[Stage]:
    """Pipeline that passes items through all stages unchanged."""
    return [Stage(_passthrough)]


def _store(path: Path) -> StorePointer:
    return StorePointer(scheme="file", remote=None, path=str(path))


def _media(path: Path) -> FileMediaSource:
    return FileMediaSource(path=str(path))


def _make_media(tmp_path: Path, filenames: list[str]) -> Path:
    """Create a media directory with empty files."""
    media = tmp_path / "media"
    media.mkdir()
    for name in filenames:
        (media / name).write_text("fake")
    return media


# ---------------------------------------------------------------------------
# IndexingRunner.run — basic orchestration
# ---------------------------------------------------------------------------


class TestIndexingRunnerBasic:
    def test_creates_db_dir(self, tmp_path: Path) -> None:
        media = _make_media(tmp_path, ["a.jpg"])
        store = _store(tmp_path / "store")
        (tmp_path / "store").mkdir()

        runner = IndexingRunner(OneByOneRunner(), checkpoint_interval=-1)
        runner.run(
            pipeline=_noop_pipeline(),
            media=_media(media),
            store=store,
            index_store=StubIndexStore(),
            index_store_name="stub",
        )

        assert (tmp_path / "store" / "db").is_dir()

    def test_writes_index_meta(self, tmp_path: Path) -> None:
        media = _make_media(tmp_path, ["a.jpg"])
        store_dir = tmp_path / "store"
        store_dir.mkdir()

        runner = IndexingRunner(OneByOneRunner(), checkpoint_interval=-1)
        runner.run(
            pipeline=_noop_pipeline(),
            media=_media(media),
            store=_store(store_dir),
            index_store=StubIndexStore(),
            index_store_name="my_indexer",
        )

        meta = IndexMeta.load(store_dir / "db" / "index_meta.json")
        assert meta.index_store == "my_indexer"

    def test_empty_media_source_completes(self, tmp_path: Path) -> None:
        media = _make_media(tmp_path, [])
        store_dir = tmp_path / "store"
        store_dir.mkdir()

        runner = IndexingRunner(OneByOneRunner(), checkpoint_interval=-1)
        runner.run(
            pipeline=_noop_pipeline(),
            media=_media(media),
            store=_store(store_dir),
            index_store=StubIndexStore(),
            index_store_name="stub",
        )

        assert (store_dir / "db").is_dir()

    def test_second_run_archives_old_db(self, tmp_path: Path) -> None:
        media = _make_media(tmp_path, ["a.jpg"])
        store_dir = tmp_path / "store"
        store_dir.mkdir()
        store = _store(store_dir)

        runner = IndexingRunner(OneByOneRunner(), checkpoint_interval=-1)
        runner.run(_noop_pipeline(), _media(media), store, StubIndexStore(), "stub")
        runner.run(_noop_pipeline(), _media(media), store, StubIndexStore(), "stub")

        archived = [d for d in store_dir.iterdir() if d.name.startswith("db_")]
        assert len(archived) >= 1


# ---------------------------------------------------------------------------
# Incremental skip
# ---------------------------------------------------------------------------


class TestIncrementalSkip:
    def test_unchanged_file_is_skipped(self, tmp_path: Path) -> None:
        media = _make_media(tmp_path, ["a.jpg"])
        store_dir = tmp_path / "store"
        store_dir.mkdir()
        store = _store(store_dir)

        # Create a fake existing db dir so _setup_db calls load_for_update
        # instead of create_empty, preserving the pre-populated stub data.
        db_dir = store_dir / "db"
        db_dir.mkdir()
        db_dir.joinpath("index_meta.json").write_text(
            json.dumps({
                "indexer_version": INDEXER_VERSION,
                "source": "file:///media",
                "index_store": "stub",
                "indexed_at": "2025-01-01T00:00:00+00:00",
            })
        )

        # Pre-populate index with a matching mtime
        mf_path = media / "a.jpg"
        idx = StubIndexStore()
        idx.create_empty()
        idx.upsert("a.jpg", "text", {"file_mtime": str(mf_path.stat().st_mtime)})

        processed: list[str] = []

        def recorder(items: list[BatchItem]) -> list[BatchItem]:
            processed.extend(item.media_file.relative_path for item in items)
            return items

        runner = IndexingRunner(OneByOneRunner(), checkpoint_interval=-1)
        runner.run(
            pipeline=[Stage(recorder)],
            media=_media(media),
            store=store,
            index_store=idx,
            index_store_name="stub",
        )

        assert "a.jpg" not in processed

    def test_changed_mtime_is_reprocessed(self, tmp_path: Path) -> None:
        media = _make_media(tmp_path, ["a.jpg"])
        store_dir = tmp_path / "store"
        store_dir.mkdir()
        store = _store(store_dir)

        # Pre-populate with a stale mtime
        idx = StubIndexStore()
        idx.create_empty()
        idx.upsert("a.jpg", "text", {"file_mtime": "0.0"})

        processed: list[str] = []

        def recorder(items: list[BatchItem]) -> list[BatchItem]:
            processed.extend(item.media_file.relative_path for item in items)
            return items

        runner = IndexingRunner(OneByOneRunner(), checkpoint_interval=-1)
        runner.run(
            pipeline=[Stage(recorder)],
            media=_media(media),
            store=store,
            index_store=idx,
            index_store_name="stub",
        )

        assert "a.jpg" in processed


# ---------------------------------------------------------------------------
# Checkpointing
# ---------------------------------------------------------------------------


class TestCheckpointing:
    def test_checkpoint_disabled(self, tmp_path: Path) -> None:
        media = _make_media(tmp_path, ["a.jpg", "b.jpg"])
        store_dir = tmp_path / "store"
        store_dir.mkdir()

        checkpoints: list[str] = []
        original_put_dir = StorePointer.put_dir

        def tracking_put_dir(self: StorePointer, src: Path, dest_name: str) -> None:
            if dest_name == "db_checkpoint":
                checkpoints.append(dest_name)
            original_put_dir(self, src, dest_name)

        runner = IndexingRunner(OneByOneRunner(), checkpoint_interval=-1)
        with patch.object(StorePointer, "put_dir", tracking_put_dir):
            runner.run(
                _noop_pipeline(),
                _media(media),
                _store(store_dir),
                StubIndexStore(),
                "stub",
            )

        assert checkpoints == []

    def test_checkpoint_every_item_when_interval_zero(self, tmp_path: Path) -> None:
        media = _make_media(tmp_path, ["a.jpg", "b.jpg"])
        store_dir = tmp_path / "store"
        store_dir.mkdir()

        checkpoints: list[str] = []
        original_put_dir = StorePointer.put_dir

        def tracking_put_dir(self: StorePointer, src: Path, dest_name: str) -> None:
            if dest_name == "db_checkpoint":
                checkpoints.append(dest_name)
            original_put_dir(self, src, dest_name)

        runner = IndexingRunner(OneByOneRunner(), checkpoint_interval=0)
        with patch.object(StorePointer, "put_dir", tracking_put_dir):
            runner.run(
                _noop_pipeline(),
                _media(media),
                _store(store_dir),
                StubIndexStore(),
                "stub",
            )

        assert len(checkpoints) >= 1

    def test_checkpoint_every_n_items(self, tmp_path: Path) -> None:
        media = _make_media(tmp_path, [f"{i}.jpg" for i in range(4)])
        store_dir = tmp_path / "store"
        store_dir.mkdir()

        checkpoints: list[str] = []
        original_put_dir = StorePointer.put_dir

        def tracking_put_dir(self: StorePointer, src: Path, dest_name: str) -> None:
            if dest_name == "db_checkpoint":
                checkpoints.append(dest_name)
            original_put_dir(self, src, dest_name)

        runner = IndexingRunner(OneByOneRunner(), checkpoint_interval=2)
        with patch.object(StorePointer, "put_dir", tracking_put_dir):
            runner.run(
                _noop_pipeline(),
                _media(media),
                _store(store_dir),
                StubIndexStore(),
                "stub",
            )

        # 4 items, interval=2 → checkpoints at item 2 and 4
        assert len(checkpoints) == 2


# ---------------------------------------------------------------------------
# AdaptiveBatchRunner integration
# ---------------------------------------------------------------------------


class TestWithAdaptiveBatchRunner:
    def test_pipeline_runner_injected_correctly(self, tmp_path: Path) -> None:
        media = _make_media(tmp_path, ["a.jpg", "b.jpg"])
        store_dir = tmp_path / "store"
        store_dir.mkdir()

        from indexer.batch import AdaptiveBatchController

        ctrl = AdaptiveBatchController(initial_size=2, max_size=2, adaptive=False)
        batch_runner = AdaptiveBatchRunner(ctrl)
        runner = IndexingRunner(batch_runner, checkpoint_interval=-1)

        runner.run(
            _noop_pipeline(),
            _media(media),
            _store(store_dir),
            StubIndexStore(),
            "stub",
        )

        assert (store_dir / "db").is_dir()
