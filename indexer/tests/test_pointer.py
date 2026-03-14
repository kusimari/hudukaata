"""Tests for pointer.py — MediaSource implementations and supporting types."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from indexer.pointer import (
    FileMediaPointer,
    GoogleColabMediaPointer,
    MediaFile,
    MediaPointer,
    MediaSource,
    RcloneMediaPointer,
    StorePointer,
    _LocalFile,
)

# ---------------------------------------------------------------------------
# Parsing — MediaPointer.parse() factory
# ---------------------------------------------------------------------------


class TestParseMediaPointer:
    def test_file_scheme(self) -> None:
        p = MediaPointer.parse("file:///tmp/media")
        assert p.scheme == "file"
        assert p.remote is None
        assert p.path == "/tmp/media"

    def test_file_scheme_returns_file_media_pointer(self) -> None:
        p = MediaPointer.parse("file:///tmp/media")
        assert isinstance(p, FileMediaPointer)

    def test_rclone_scheme(self) -> None:
        p = MediaPointer.parse("rclone:my-remote:///path/on/remote")
        assert p.scheme == "rclone"
        assert p.remote == "my-remote"
        assert p.path == "path/on/remote"

    def test_rclone_scheme_returns_rclone_media_pointer(self) -> None:
        p = MediaPointer.parse("rclone:gdrive:///photos")
        assert isinstance(p, RcloneMediaPointer)

    def test_rclone_single_slash(self) -> None:
        p = MediaPointer.parse("rclone:gdrive:/photos")
        assert p.scheme == "rclone"
        assert p.remote == "gdrive"
        assert p.path == "photos"

    def test_rclone_dotted_remote_name(self) -> None:
        p = MediaPointer.parse("rclone:my.remote:///path")
        assert p.remote == "my.remote"

    def test_unsupported_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported URI scheme"):
            MediaPointer.parse("s3://bucket/path")


class TestParseStorePointer:
    def test_file_scheme(self) -> None:
        p = StorePointer.parse("file:///tmp/store")
        assert p.scheme == "file"
        assert p.remote is None
        assert p.path == "/tmp/store"

    def test_rclone_scheme(self) -> None:
        p = StorePointer.parse("rclone:backup:///db")
        assert p.scheme == "rclone"
        assert p.remote == "backup"
        assert p.path == "db"


# ---------------------------------------------------------------------------
# URI property
# ---------------------------------------------------------------------------


class TestUri:
    def test_file_uri_roundtrip(self) -> None:
        p = MediaPointer.parse("file:///some/path")
        assert p.uri == "file:///some/path"

    def test_rclone_uri_roundtrip(self) -> None:
        p = MediaPointer.parse("rclone:gdrive:///photos")
        assert p.uri == "rclone:gdrive:///photos"

    def test_store_pointer_uri(self) -> None:
        p = StorePointer.parse("file:///tmp/store")
        assert p.uri == "file:///tmp/store"

    def test_file_media_pointer_uri(self) -> None:
        p = FileMediaPointer(path="/data/photos")
        assert p.uri == "file:///data/photos"

    def test_rclone_media_pointer_uri(self) -> None:
        p = RcloneMediaPointer(remote="gdrive", path="photos")
        assert p.uri == "rclone:gdrive:///photos"


# ---------------------------------------------------------------------------
# MediaFile — context manager behaviour
# ---------------------------------------------------------------------------


class TestMediaFile:
    def test_local_path_raises_outside_context(self, tmp_path: Path) -> None:
        path = tmp_path / "img.jpg"
        path.write_bytes(b"x")
        mf = MediaFile("img.jpg", "image", _LocalFile(path))
        with pytest.raises(RuntimeError, match="with mf"):
            _ = mf.local_path

    def test_local_path_accessible_inside_context(self, tmp_path: Path) -> None:
        path = tmp_path / "img.jpg"
        path.write_bytes(b"x")
        mf = MediaFile("img.jpg", "image", _LocalFile(path))
        with mf:
            assert mf.local_path == path

    def test_local_path_invalid_after_context_exits(self, tmp_path: Path) -> None:
        path = tmp_path / "img.jpg"
        path.write_bytes(b"x")
        mf = MediaFile("img.jpg", "image", _LocalFile(path))
        with mf:
            pass
        with pytest.raises(RuntimeError):
            _ = mf.local_path

    def test_enter_returns_self(self, tmp_path: Path) -> None:
        path = tmp_path / "img.jpg"
        path.write_bytes(b"x")
        mf = MediaFile("img.jpg", "image", _LocalFile(path))
        with mf as entered:
            assert entered is mf


# ---------------------------------------------------------------------------
# FileMediaPointer.scan()
# ---------------------------------------------------------------------------


class TestFileMediaPointerScan:
    def test_is_media_source(self, tmp_path: Path) -> None:
        assert isinstance(FileMediaPointer(path=str(tmp_path)), MediaSource)

    def test_relative_path_raises(self) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            FileMediaPointer(path="relative/path")

    def test_filters_to_known_media_types(self, tmp_path: Path) -> None:
        (tmp_path / "photo.jpg").write_bytes(b"x")
        (tmp_path / "clip.mp4").write_bytes(b"x")
        (tmp_path / "song.mp3").write_bytes(b"x")
        (tmp_path / "readme.txt").write_bytes(b"x")

        p = FileMediaPointer(path=str(tmp_path))
        files = list(p.scan())

        exts = {f.relative_path.split(".")[-1] for f in files}
        assert exts == {"jpg", "mp4", "mp3"}
        assert "readme.txt" not in {f.relative_path for f in files}

    def test_media_types_assigned_correctly(self, tmp_path: Path) -> None:
        (tmp_path / "img.jpg").write_bytes(b"x")
        (tmp_path / "vid.mp4").write_bytes(b"x")
        (tmp_path / "aud.wav").write_bytes(b"x")

        p = FileMediaPointer(path=str(tmp_path))
        by_name = {f.relative_path: f.media_type for f in p.scan()}

        assert by_name["img.jpg"] == "image"
        assert by_name["vid.mp4"] == "video"
        assert by_name["aud.wav"] == "audio"

    def test_nested_directories(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "nested.png").write_bytes(b"x")

        p = FileMediaPointer(path=str(tmp_path))
        files = list(p.scan())
        assert any(f.relative_path == "sub/nested.png" for f in files)

    def test_local_path_accessible_inside_with_block(self, tmp_path: Path) -> None:
        (tmp_path / "img.jpg").write_bytes(b"x")
        p = FileMediaPointer(path=str(tmp_path))
        for mf in p.scan():
            with mf:
                assert mf.local_path.exists()

    def test_empty_directory(self, tmp_path: Path) -> None:
        p = FileMediaPointer(path=str(tmp_path))
        assert list(p.scan()) == []

    def test_subfolder_limits_scan(self, tmp_path: Path) -> None:
        (tmp_path / "root.jpg").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "child.png").write_bytes(b"x")

        p = FileMediaPointer(path=str(tmp_path))
        files = list(p.scan(subfolder="sub"))

        paths = {f.relative_path for f in files}
        assert paths == {"sub/child.png"}
        assert "root.jpg" not in paths

    def test_subfolder_relative_path_is_relative_to_root(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "img.png").write_bytes(b"x")

        p = FileMediaPointer(path=str(tmp_path))
        files = list(p.scan(subfolder="sub"))

        assert len(files) == 1
        assert files[0].relative_path == "sub/img.png"

    def test_subfolder_nonexistent_yields_nothing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        p = FileMediaPointer(path=str(tmp_path))
        with caplog.at_level(logging.WARNING, logger="indexer.pointer"):
            files = list(p.scan(subfolder="does_not_exist"))

        assert files == []
        assert any("does_not_exist" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# scan() — backward-compat via MediaPointer.parse (file://)
# ---------------------------------------------------------------------------


class TestMediaPointerShim:
    """Tests for the MediaPointer backward-compat shim (direct construction + scan)."""

    def test_rclone_scan_delegates(self) -> None:
        """MediaPointer(scheme='rclone').scan() delegates to RcloneMediaPointer."""
        entries = [{"Path": "a.jpg", "IsDir": False, "ModTime": "2024-01-01T00:00:00Z"}]
        mp = MediaPointer(scheme="rclone", remote="r", path="p")
        with patch("indexer.pointer._rclone_lsjson", return_value=entries):
            files = list(mp.scan())

        assert len(files) == 1
        assert files[0].relative_path == "a.jpg"
        assert files[0].media_type == "image"


class TestScan:
    """Ensure MediaPointer.parse() + scan() still works end-to-end."""

    def test_filters_to_known_media_types(self, tmp_path: Path) -> None:
        (tmp_path / "photo.jpg").write_bytes(b"x")
        (tmp_path / "clip.mp4").write_bytes(b"x")
        (tmp_path / "song.mp3").write_bytes(b"x")
        (tmp_path / "readme.txt").write_bytes(b"x")

        p = MediaPointer.parse(f"file://{tmp_path}")
        files = list(p.scan())

        exts = {f.relative_path.split(".")[-1] for f in files}
        assert exts == {"jpg", "mp4", "mp3"}
        assert "readme.txt" not in {f.relative_path for f in files}

    def test_empty_directory(self, tmp_path: Path) -> None:
        p = MediaPointer.parse(f"file://{tmp_path}")
        assert list(p.scan()) == []

    def test_subfolder_limits_scan(self, tmp_path: Path) -> None:
        (tmp_path / "root.jpg").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "child.png").write_bytes(b"x")

        p = MediaPointer.parse(f"file://{tmp_path}")
        files = list(p.scan(subfolder="sub"))

        paths = {f.relative_path for f in files}
        assert paths == {"sub/child.png"}
        assert "root.jpg" not in paths

    def test_subfolder_nonexistent_yields_nothing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        p = MediaPointer.parse(f"file://{tmp_path}")
        with caplog.at_level(logging.WARNING, logger="indexer.pointer"):
            files = list(p.scan(subfolder="does_not_exist"))

        assert files == []
        assert any("does_not_exist" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# RcloneMediaPointer
# ---------------------------------------------------------------------------


class TestRcloneMediaPointer:
    def test_is_media_source(self) -> None:
        assert isinstance(RcloneMediaPointer(remote="gdrive", path="photos"), MediaSource)

    def test_uri(self) -> None:
        p = RcloneMediaPointer(remote="gdrive", path="photos")
        assert p.uri == "rclone:gdrive:///photos"

    def test_scheme_and_attrs(self) -> None:
        p = RcloneMediaPointer(remote="backup", path="data")
        assert p.scheme == "rclone"
        assert p.remote == "backup"
        assert p.path == "data"

    def test_scan_yields_media_files(self) -> None:
        """scan() calls _rclone_lsjson and yields MediaFiles for recognised media."""
        entries = [
            {"Path": "vacation.jpg", "IsDir": False, "ModTime": "2024-06-01T10:00:00Z"},
            {"Path": "notes.txt", "IsDir": False, "ModTime": "2024-06-01T10:00:00Z"},
            {"Path": "subdir", "IsDir": True},
        ]
        p = RcloneMediaPointer(remote="gdrive", path="photos")
        with patch("indexer.pointer._rclone_lsjson", return_value=entries):
            files = list(p.scan())

        assert len(files) == 1
        assert files[0].relative_path == "vacation.jpg"
        assert files[0].media_type == "image"

    def test_scan_subfolder_prepends_prefix(self) -> None:
        """scan(subfolder=...) yields paths relative to the original root."""
        entries = [
            {"Path": "img.jpg", "IsDir": False, "ModTime": "2024-01-01T00:00:00Z"},
        ]
        p = RcloneMediaPointer(remote="gdrive", path="photos")
        with patch("indexer.pointer._rclone_lsjson", return_value=entries):
            files = list(p.scan(subfolder="2024"))

        assert files[0].relative_path == "2024/img.jpg"

    def test_scan_skips_directories(self) -> None:
        entries = [
            {"Path": "dir", "IsDir": True},
            {"Path": "a.jpg", "IsDir": False, "ModTime": "2024-01-01T00:00:00Z"},
        ]
        p = RcloneMediaPointer(remote="r", path="p")
        with patch("indexer.pointer._rclone_lsjson", return_value=entries):
            files = list(p.scan())

        assert len(files) == 1

    def test_scan_skips_unknown_extensions(self) -> None:
        entries = [{"Path": "doc.pdf", "IsDir": False, "ModTime": "2024-01-01T00:00:00Z"}]
        p = RcloneMediaPointer(remote="r", path="p")
        with patch("indexer.pointer._rclone_lsjson", return_value=entries):
            files = list(p.scan())

        assert files == []

    def test_scan_mtime_parsed_from_iso(self) -> None:
        entries = [{"Path": "a.jpg", "IsDir": False, "ModTime": "2024-06-01T00:00:00Z"}]
        p = RcloneMediaPointer(remote="r", path="p")
        with patch("indexer.pointer._rclone_lsjson", return_value=entries):
            files = list(p.scan())

        assert files[0].mtime is not None
        assert files[0].mtime > 0

    def test_scan_mtime_none_when_missing(self) -> None:
        entries = [{"Path": "a.jpg", "IsDir": False}]
        p = RcloneMediaPointer(remote="r", path="p")
        with patch("indexer.pointer._rclone_lsjson", return_value=entries):
            files = list(p.scan())

        assert files[0].mtime is None


# ---------------------------------------------------------------------------
# GoogleColabMediaPointer
# ---------------------------------------------------------------------------


def _setup_colab_mock(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """Install a mock google.colab.drive module; return the mount_calls list."""
    mount_calls: list[tuple[str, bool]] = []
    mock_drive = types.ModuleType("drive")

    def mock_mount(path: str, *, force_remount: bool = False, **_: object) -> None:
        mount_calls.append((path, force_remount))

    mock_drive.mount = mock_mount  # type: ignore[attr-defined]
    mock_colab = types.ModuleType("google.colab")
    mock_colab.drive = mock_drive  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google.colab", mock_colab)
    monkeypatch.setitem(sys.modules, "google.colab.drive", mock_drive)
    return mount_calls


class TestGoogleColabMediaPointer:
    def test_is_media_source(self) -> None:
        assert isinstance(GoogleColabMediaPointer(), MediaSource)

    def test_uri_empty_path(self) -> None:
        assert GoogleColabMediaPointer().uri == "gdrive:///"

    def test_uri_with_path(self) -> None:
        assert GoogleColabMediaPointer("vacation/2024").uri == "gdrive:///vacation/2024"

    def test_uri_strips_leading_slash(self) -> None:
        assert GoogleColabMediaPointer("/photos").uri == "gdrive:///photos"

    def test_scan_raises_outside_colab(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "google.colab", None)  # type: ignore[arg-type]
        with pytest.raises(ImportError, match="google-colab"):
            list(GoogleColabMediaPointer().scan())

    def test_scan_mounts_drive(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mount_calls = _setup_colab_mock(monkeypatch)
        monkeypatch.setattr(GoogleColabMediaPointer, "_MOUNT_POINT", tmp_path)

        list(GoogleColabMediaPointer().scan())

        assert mount_calls == [("/content/drive", False)]

    def test_scan_force_remount_is_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mount_calls = _setup_colab_mock(monkeypatch)
        monkeypatch.setattr(GoogleColabMediaPointer, "_MOUNT_POINT", tmp_path)

        list(GoogleColabMediaPointer().scan())

        assert mount_calls[0][1] is False

    def test_scan_yields_media_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _setup_colab_mock(monkeypatch)
        monkeypatch.setattr(GoogleColabMediaPointer, "_MOUNT_POINT", tmp_path)
        (tmp_path / "photo.jpg").write_bytes(b"x")
        (tmp_path / "clip.mp4").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")

        files = list(GoogleColabMediaPointer().scan())

        exts = {f.relative_path.split(".")[-1] for f in files}
        assert exts == {"jpg", "mp4"}

    def test_scan_uses_drive_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """scan() navigates _MOUNT_POINT / drive_path."""
        _setup_colab_mock(monkeypatch)
        monkeypatch.setattr(GoogleColabMediaPointer, "_MOUNT_POINT", tmp_path)
        sub = tmp_path / "vacation"
        sub.mkdir()
        (sub / "beach.jpg").write_bytes(b"x")

        files = list(GoogleColabMediaPointer("vacation").scan())

        assert len(files) == 1
        assert files[0].relative_path == "beach.jpg"

    def test_scan_subfolder_relative_to_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _setup_colab_mock(monkeypatch)
        monkeypatch.setattr(GoogleColabMediaPointer, "_MOUNT_POINT", tmp_path)
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "img.png").write_bytes(b"x")
        (tmp_path / "root.jpg").write_bytes(b"x")

        files = list(GoogleColabMediaPointer().scan(subfolder="sub"))

        paths = {f.relative_path for f in files}
        assert paths == {"sub/img.png"}

    def test_scan_nonexistent_subfolder_warns(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        _setup_colab_mock(monkeypatch)
        monkeypatch.setattr(GoogleColabMediaPointer, "_MOUNT_POINT", tmp_path)

        with caplog.at_level(logging.WARNING, logger="indexer.pointer"):
            files = list(GoogleColabMediaPointer().scan(subfolder="missing"))

        assert files == []
        assert any("missing" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# StorePointer — local filesystem operations
# ---------------------------------------------------------------------------


class TestStorePointer:
    def test_has_dir_true(self, tmp_path: Path) -> None:
        (tmp_path / "db").mkdir()
        store = StorePointer.parse(f"file://{tmp_path}")
        assert store.has_dir("db") is True

    def test_has_dir_false(self, tmp_path: Path) -> None:
        store = StorePointer.parse(f"file://{tmp_path}")
        assert store.has_dir("db") is False

    def test_put_and_get_dir(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "data.txt").write_text("hello")

        store_root = tmp_path / "store"
        store_root.mkdir()
        store = StorePointer.parse(f"file://{store_root}")

        store.put_dir(src, dest_name="uploaded")
        assert (store_root / "uploaded" / "data.txt").read_text() == "hello"

        local = store.get_dir("uploaded")
        assert (local / "data.txt").read_text() == "hello"

    def test_get_dir_ctx_yields_path(self, tmp_path: Path) -> None:
        (tmp_path / "db").mkdir()
        (tmp_path / "db" / "data.txt").write_text("ok")
        store = StorePointer.parse(f"file://{tmp_path}")
        with store.get_dir_ctx("db") as p:
            assert (p / "data.txt").read_text() == "ok"

    def test_rename_dir(self, tmp_path: Path) -> None:
        (tmp_path / "old").mkdir()
        store = StorePointer.parse(f"file://{tmp_path}")
        store.rename_dir("old", "new")
        assert not (tmp_path / "old").exists()
        assert (tmp_path / "new").is_dir()

    def test_delete_dir(self, tmp_path: Path) -> None:
        (tmp_path / "target").mkdir()
        store = StorePointer.parse(f"file://{tmp_path}")
        store.delete_dir("target")
        assert not (tmp_path / "target").exists()

    def test_delete_dir_noop_when_missing(self, tmp_path: Path) -> None:
        store = StorePointer.parse(f"file://{tmp_path}")
        store.delete_dir("nonexistent")  # should not raise
