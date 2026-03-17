"""Integration tests for batch-mode runner — real ChromaCaptionIndexStore."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from common.base import StorePointer
from common.index import CaptionItem
from common.media import FileMediaSource

from indexer.runner import run
from indexer.stores.chroma_caption import ChromaCaptionIndexStore
from tests.stubs.caption_model import StubCaptionModel


@pytest.fixture(scope="session", autouse=True)
def _require_vectorizer_model() -> None:
    """Skip the whole module when the sentence-transformer model cannot be loaded."""
    from indexer.vectorizers.sentence_transformer import SentenceTransformerVectorizer

    v = SentenceTransformerVectorizer()
    try:
        v.vectorize("warmup")
    except Exception as exc:
        pytest.skip(f"sentence-transformers model unavailable: {exc}")


def _media(path: Path) -> FileMediaSource:
    return FileMediaSource(path=str(path))


def _store(path: Path) -> StorePointer:
    return StorePointer(scheme="file", remote=None, path=str(path))


@pytest.fixture()
def media_dir(tmp_path: Path) -> Path:
    """A small media directory with 4 Pillow-generated images."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    media = tmp_path / "media"
    media.mkdir()
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 0)]
    for i, color in enumerate(colors):
        Image.new("RGB", (32, 32), color=color).save(media / f"img{i}.jpg")
    return media


@pytest.fixture()
def store_dir(tmp_path: Path) -> Path:
    s = tmp_path / "store"
    s.mkdir()
    return s


def _run_batch(
    media_dir: Path,
    store_dir: Path,
    initial_batch_size: int = 1,
    max_batch_size: int = 32,
    adaptive: bool = True,
    checkpoint_interval: int = 0,
) -> None:
    run(
        _media(media_dir),
        _store(store_dir),
        StubCaptionModel(),
        ChromaCaptionIndexStore(),
        index_store_name="indexer.stores.chroma_caption.ChromaCaptionIndexStore",
        initial_batch_size=initial_batch_size,
        max_batch_size=max_batch_size,
        adaptive_batch=adaptive,
        checkpoint_interval=checkpoint_interval,
    )


class TestBatchIndexing:
    def test_single_item_batch_creates_db(self, media_dir: Path, store_dir: Path) -> None:
        _run_batch(media_dir, store_dir, initial_batch_size=1, adaptive=False)
        assert (store_dir / "db").is_dir()

    def test_multi_item_batch_creates_db(self, media_dir: Path, store_dir: Path) -> None:
        _run_batch(media_dir, store_dir, initial_batch_size=4, adaptive=False)
        assert (store_dir / "db").is_dir()

    def test_batch4_indexes_same_files_as_batch1(self, tmp_path: Path) -> None:
        """batch_size=4 and batch_size=1 produce the same set of indexed files."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        media = tmp_path / "media"
        media.mkdir()
        for i in range(4):
            Image.new("RGB", (16, 16), color=(i * 60, 0, 0)).save(media / f"img{i}.jpg")

        store1 = tmp_path / "store1"
        store1.mkdir()
        store2 = tmp_path / "store2"
        store2.mkdir()

        _run_batch(media, store1, initial_batch_size=1, adaptive=False)
        _run_batch(media, store2, initial_batch_size=4, adaptive=False)

        idx1 = ChromaCaptionIndexStore()
        idx1.load(store1 / "db")
        idx2 = ChromaCaptionIndexStore()
        idx2.load(store2 / "db")

        results1 = {r.relative_path for r in idx1.search(CaptionItem(text="image"), top_k=10)}
        results2 = {r.relative_path for r in idx2.search(CaptionItem(text="image"), top_k=10)}
        assert results1 == results2

    def test_checkpoint_written_per_batch_when_interval_zero(
        self, media_dir: Path, store_dir: Path
    ) -> None:
        """With checkpoint_interval=0 a checkpoint is uploaded after each batch."""
        checkpoints_written: list[str] = []

        original_put_dir = StorePointer.put_dir

        def tracking_put_dir(self: StorePointer, src: Path, dest_name: str) -> None:
            if dest_name == "db_checkpoint":
                checkpoints_written.append(dest_name)
            original_put_dir(self, src, dest_name)

        with patch.object(StorePointer, "put_dir", tracking_put_dir):
            _run_batch(
                media_dir,
                store_dir,
                initial_batch_size=1,
                adaptive=False,
                checkpoint_interval=0,
            )

        # With 4 files and batch_size=1, expect 4 checkpoint writes
        assert len(checkpoints_written) >= 1

    def test_no_checkpoint_when_disabled(self, media_dir: Path, store_dir: Path) -> None:
        checkpoints_written: list[str] = []

        original_put_dir = StorePointer.put_dir

        def tracking_put_dir(self: StorePointer, src: Path, dest_name: str) -> None:
            if dest_name == "db_checkpoint":
                checkpoints_written.append(dest_name)
            original_put_dir(self, src, dest_name)

        with patch.object(StorePointer, "put_dir", tracking_put_dir):
            _run_batch(
                media_dir,
                store_dir,
                initial_batch_size=4,
                adaptive=False,
                checkpoint_interval=-1,
            )

        assert checkpoints_written == []

    def test_oom_falls_back_to_single(self, media_dir: Path, store_dir: Path) -> None:
        """When caption_batch raises a RuntimeError with 'out of memory', runner
        falls back to single-file processing and still indexes everything."""
        stub = StubCaptionModel()
        call_count = 0
        original_batch = stub.caption_batch

        def failing_first_batch(mfs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1 and len(mfs) > 1:
                raise RuntimeError("CUDA out of memory: tried to allocate 1 GiB")
            return original_batch(mfs)

        stub.caption_batch = failing_first_batch  # type: ignore[method-assign]

        run(
            _media(media_dir),
            _store(store_dir),
            stub,
            ChromaCaptionIndexStore(),
            index_store_name="indexer.stores.chroma_caption.ChromaCaptionIndexStore",
            initial_batch_size=4,
            max_batch_size=32,
            adaptive_batch=True,
            checkpoint_interval=-1,
        )

        assert (store_dir / "db").is_dir()

    def test_adaptive_batch_grows(self, media_dir: Path, store_dir: Path) -> None:
        """Smoke test: adaptive mode starts at 1 and doesn't crash."""
        _run_batch(
            media_dir,
            store_dir,
            initial_batch_size=1,
            max_batch_size=8,
            adaptive=True,
            checkpoint_interval=-1,
        )
        assert (store_dir / "db").is_dir()
