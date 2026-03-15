"""Unit tests for incremental-update behaviour in runner.py.

These tests use stubs only (no real ChromaDB, no real models).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from common.base import INDEXER_VERSION, IndexMeta, StorePointer

from indexer.runner import _run
from tests.stubs.caption_model import StubCaptionModel
from tests.stubs.index_store import StubIndexStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store(path: Path) -> StorePointer:
    return StorePointer(scheme="file", remote=None, path=str(path))


def _make_media_dir(root: Path, files: list[str]) -> Path:
    """Create PNG stubs at *root/<file>* and return *root*."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    root.mkdir(parents=True, exist_ok=True)
    for rel in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), color=(100, 100, 100)).save(p)
    return root


def _write_db_meta(db_path: Path, version: str = INDEXER_VERSION) -> None:
    """Write a minimal index_meta.json into db_path."""
    from datetime import UTC, datetime

    db_path.mkdir(parents=True, exist_ok=True)
    meta = IndexMeta(
        indexed_at=datetime.now(UTC),
        source="file:///test",
        index_store="indexer.stores.chroma_caption.ChromaCaptionIndexStore",
        indexer_version=version,
    )
    meta.save(db_path / "index_meta.json")


def _make_run_args(
    media_path: Path,
    store_path: Path,
    local_tmp: Path,
    index_store: StubIndexStore | None = None,
    caption_model: StubCaptionModel | None = None,
    folder: str | None = None,
    checkpoint_interval: int = 0,
) -> dict:
    from indexer.pointer import MediaPointer

    return dict(
        media=MediaPointer(scheme="file", remote=None, path=str(media_path)),
        store=_store(store_path),
        caption_model=caption_model or StubCaptionModel(),
        index_store=index_store or StubIndexStore(),
        local_tmp=local_tmp,
        index_store_name="stub",
        folder=folder,
        checkpoint_interval=checkpoint_interval,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUnchangedFileSkipped:
    def test_unchanged_file_not_recaptioned(self, tmp_path: Path) -> None:
        """A file already indexed with matching mtime should not be processed."""
        media = _make_media_dir(tmp_path / "media", ["a.png"])
        store_path = tmp_path / "store"
        store_path.mkdir()
        local_tmp = tmp_path / "work"
        local_tmp.mkdir()

        img_path = media / "a.png"
        mtime = img_path.stat().st_mtime

        # Pre-populate stub store with this file's mtime.
        idx = StubIndexStore()
        idx.docs["a.png"] = (
            "old caption",
            {"caption": "old", "relative_path": "a.png", "file_mtime": str(mtime)},
        )

        # Put a "db" dir in the store with matching indexer_version.
        db_path = store_path / "db"
        db_path.mkdir()
        _write_db_meta(db_path)

        caption_model = StubCaptionModel()
        call_tracker: list[str] = []
        original_caption = caption_model.caption

        def tracking_caption(mf):  # type: ignore[no-untyped-def]
            call_tracker.append(mf.relative_path)
            return original_caption(mf)

        caption_model.caption = tracking_caption  # type: ignore[method-assign]

        _run(**_make_run_args(media, store_path, local_tmp, idx, caption_model))

        assert "a.png" not in call_tracker, "unchanged file should have been skipped"

    def test_changed_file_is_reprocessed(self, tmp_path: Path) -> None:
        """A file with a different mtime must be re-captioned and re-indexed."""
        media = _make_media_dir(tmp_path / "media", ["b.png"])
        store_path = tmp_path / "store"
        store_path.mkdir()
        local_tmp = tmp_path / "work"
        local_tmp.mkdir()

        idx = StubIndexStore()
        # Store a stale mtime (0.0) so the file always appears changed.
        idx.docs["b.png"] = (
            "stale caption",
            {"caption": "stale", "relative_path": "b.png", "file_mtime": "0.0"},
        )

        db_path = store_path / "db"
        db_path.mkdir()
        _write_db_meta(db_path)

        caption_model = StubCaptionModel()
        call_tracker: list[str] = []
        original_caption = caption_model.caption

        def tracking_caption(mf):  # type: ignore[no-untyped-def]
            call_tracker.append(mf.relative_path)
            return original_caption(mf)

        caption_model.caption = tracking_caption  # type: ignore[method-assign]

        _run(**_make_run_args(media, store_path, local_tmp, idx, caption_model))

        assert "b.png" in call_tracker, "changed file must be reprocessed"


class TestVersionForcesFullReindex:
    def test_version_mismatch_calls_create_empty(self, tmp_path: Path) -> None:
        """When stored version != INDEXER_VERSION, create_empty is called."""
        media = _make_media_dir(tmp_path / "media", ["c.png"])
        store_path = tmp_path / "store"
        store_path.mkdir()
        local_tmp = tmp_path / "work"
        local_tmp.mkdir()

        idx = StubIndexStore()
        # Store a doc that should be skipped if version matched — but it won't.
        img_path = media / "c.png"
        mtime = img_path.stat().st_mtime
        idx.docs["c.png"] = (
            "old caption",
            {"caption": "old", "relative_path": "c.png", "file_mtime": str(mtime)},
        )

        db_path = store_path / "db"
        db_path.mkdir()
        # Write OLD version to force full reindex.
        _write_db_meta(db_path, version="0.0.0")

        create_empty_calls: list[None] = []
        original_create_empty = idx.create_empty

        def tracking_create_empty() -> None:
            create_empty_calls.append(None)
            idx.docs = {}
            original_create_empty()

        idx.create_empty = tracking_create_empty  # type: ignore[method-assign]

        caption_model = StubCaptionModel()
        call_tracker: list[str] = []

        def tracking_caption(mf):  # type: ignore[no-untyped-def]
            call_tracker.append(mf.relative_path)
            return mf.relative_path

        caption_model.caption = tracking_caption  # type: ignore[method-assign]

        _run(**_make_run_args(media, store_path, local_tmp, idx, caption_model))

        assert len(create_empty_calls) >= 1, "create_empty must be called on version mismatch"
        assert "c.png" in call_tracker, "all files must be reprocessed on version mismatch"


class TestFolderScopedScan:
    def test_folder_limits_scan(self, tmp_path: Path) -> None:
        """With folder='sub', only files under media/sub/ are processed."""
        media_root = tmp_path / "media"
        _make_media_dir(media_root, ["root.png", "sub/child.png"])
        store_path = tmp_path / "store"
        store_path.mkdir()
        local_tmp = tmp_path / "work"
        local_tmp.mkdir()

        idx = StubIndexStore()
        caption_model = StubCaptionModel()
        processed: list[str] = []

        def tracking_caption(mf):  # type: ignore[no-untyped-def]
            processed.append(mf.relative_path)
            return mf.relative_path

        caption_model.caption = tracking_caption  # type: ignore[method-assign]

        _run(**_make_run_args(media_root, store_path, local_tmp, idx, caption_model, folder="sub"))

        assert all("sub/" in p for p in processed), f"Expected only sub/ files, got: {processed}"
        assert not any(p == "root.png" for p in processed)


class TestMtimeStoredInMetadata:
    def test_file_mtime_key_in_metadata(self, tmp_path: Path) -> None:
        media = _make_media_dir(tmp_path / "media", ["img.png"])
        store_path = tmp_path / "store"
        store_path.mkdir()
        local_tmp = tmp_path / "work"
        local_tmp.mkdir()

        idx = StubIndexStore()
        _run(**_make_run_args(media, store_path, local_tmp, idx))

        assert "img.png" in idx.docs
        meta = idx.docs["img.png"][1]
        assert "file_mtime" in meta
        assert meta["file_mtime"] != ""


class TestCheckpointWritten:
    def test_checkpoint_written_after_n_files(self, tmp_path: Path) -> None:
        """Checkpoint is called after every checkpoint_interval files."""
        # Create 3 images.
        media = _make_media_dir(tmp_path / "media", ["a.png", "b.png", "c.png"])
        store_path = tmp_path / "store"
        store_path.mkdir()
        local_tmp = tmp_path / "work"
        local_tmp.mkdir()

        idx = StubIndexStore()
        checkpoint_calls: list[Path] = []
        original_checkpoint = idx.checkpoint

        def tracking_checkpoint(path: Path) -> None:
            checkpoint_calls.append(path)
            original_checkpoint(path)

        idx.checkpoint = tracking_checkpoint  # type: ignore[method-assign]

        # interval=1 → checkpoint after every file.
        _run(**_make_run_args(media, store_path, local_tmp, idx, checkpoint_interval=1))

        assert len(checkpoint_calls) == 3, (
            f"Expected 3 checkpoint calls, got {len(checkpoint_calls)}"
        )

    def test_checkpoint_written_to_store(self, tmp_path: Path) -> None:
        """After checkpointing, store/db_checkpoint exists."""
        media = _make_media_dir(tmp_path / "media", ["x.png"])
        store_path = tmp_path / "store"
        store_path.mkdir()
        local_tmp = tmp_path / "work"
        local_tmp.mkdir()

        idx = StubIndexStore()
        _run(**_make_run_args(media, store_path, local_tmp, idx, checkpoint_interval=1))

        assert (store_path / "db_checkpoint").is_dir()
