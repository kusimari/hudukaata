"""Tests for MediaFile, MediaSource, FileMediaSource, RcloneMediaSource, GdriveMediaSource."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from common.media import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    FileMediaSource,
    GdriveMediaSource,
    MediaFile,
    MediaSource,
    RcloneMediaSource,
    _LocalFile,
)

# ---------------------------------------------------------------------------
# Extension sets
# ---------------------------------------------------------------------------


class TestExtensionSets:
    def test_image_extensions_contain_jpg(self) -> None:
        assert ".jpg" in IMAGE_EXTENSIONS

    def test_video_extensions_contain_mp4(self) -> None:
        assert ".mp4" in VIDEO_EXTENSIONS

    def test_audio_extensions_contain_mp3(self) -> None:
        assert ".mp3" in AUDIO_EXTENSIONS


# ---------------------------------------------------------------------------
# MediaSource.from_uri() factory
# ---------------------------------------------------------------------------


class TestMediaSourceFromUri:
    def test_file_scheme(self) -> None:
        src = MediaSource.from_uri("file:///tmp/media")
        assert isinstance(src, FileMediaSource)
        assert src.path == "/tmp/media"

    def test_file_relative_raises(self) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            MediaSource.from_uri("file://relative/path")

    def test_unknown_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported URI scheme"):
            MediaSource.from_uri("s3://bucket/path")

    def test_uri_roundtrip(self) -> None:
        uri = "file:///tmp/media"
        assert MediaSource.from_uri(uri).uri == uri


# ---------------------------------------------------------------------------
# MediaFile context-manager behaviour
# ---------------------------------------------------------------------------


class TestMediaFile:
    def test_local_path_raises_outside_context(self, tmp_path: Path) -> None:
        mf = MediaFile("img.jpg", "image", _LocalFile(tmp_path / "img.jpg"))
        with pytest.raises(RuntimeError, match="local_path"):
            _ = mf.local_path

    def test_local_path_accessible_inside_context(self, tmp_path: Path) -> None:
        path = tmp_path / "img.jpg"
        path.write_bytes(b"x")
        mf = MediaFile("img.jpg", "image", _LocalFile(path))
        with mf:
            assert mf.local_path == path

    def test_enter_returns_self(self, tmp_path: Path) -> None:
        path = tmp_path / "img.jpg"
        path.write_bytes(b"x")
        mf = MediaFile("img.jpg", "image", _LocalFile(path))
        with mf as entered:
            assert entered is mf


# ---------------------------------------------------------------------------
# Shared harness for local-filesystem MediaSources
#
# Both FileMediaSource and GdriveMediaSource scan a local directory tree.
# Subclasses implement _src(root, monkeypatch) to return a configured source.
# ---------------------------------------------------------------------------


def _setup_colab_mock(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """Install a mock google.colab.drive module; return mount_calls list."""
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


class _LocalFsHarness:
    """Shared scan/getmedia tests for any MediaSource that reads a local FS root.

    Subclasses implement ``_src(root, monkeypatch)`` and optionally override
    tests that don't apply to their type.
    """

    def _src(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> MediaSource:
        raise NotImplementedError

    # --- scan ---

    def test_scan_yields_image(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "img.jpg").write_bytes(b"x")
        files = list(self._src(tmp_path, monkeypatch).scan())
        assert len(files) == 1
        assert files[0].relative_path == "img.jpg"
        assert files[0].media_type == "image"

    def test_scan_yields_all_media_types(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "img.jpg").write_bytes(b"x")
        (tmp_path / "vid.mp4").write_bytes(b"x")
        (tmp_path / "aud.mp3").write_bytes(b"x")
        types_ = {f.media_type for f in self._src(tmp_path, monkeypatch).scan()}
        assert types_ == {"image", "video", "audio"}

    def test_scan_excludes_non_media(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "img.jpg").write_bytes(b"x")
        (tmp_path / "readme.txt").write_bytes(b"x")
        files = list(self._src(tmp_path, monkeypatch).scan())
        assert {f.relative_path for f in files} == {"img.jpg"}

    def test_scan_nested_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b.png").write_bytes(b"x")
        files = list(self._src(tmp_path, monkeypatch).scan())
        assert any(f.relative_path == "a/b.png" for f in files)

    def test_scan_relative_path_relative_to_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a" / "b").mkdir(parents=True)
        (tmp_path / "a" / "b" / "img.jpg").write_bytes(b"x")
        files = list(self._src(tmp_path, monkeypatch).scan())
        assert files[0].relative_path == "a/b/img.jpg"

    def test_scan_subfolder_limits_results(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "img.png").write_bytes(b"x")
        (tmp_path / "root.jpg").write_bytes(b"x")
        files = list(self._src(tmp_path, monkeypatch).scan(subfolder="sub"))
        assert {f.relative_path for f in files} == {"sub/img.png"}

    def test_scan_mediafile_is_context_manager(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "img.jpg").write_bytes(b"x")
        [mf] = list(self._src(tmp_path, monkeypatch).scan())
        with mf:
            assert mf.local_path.exists()

    # --- getmedia ---

    def test_getmedia_returns_mediafile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "img.jpg").write_bytes(b"x")
        mf = self._src(tmp_path, monkeypatch).getmedia("img.jpg")
        assert isinstance(mf, MediaFile)
        assert mf.relative_path == "img.jpg"

    def test_getmedia_context_manager(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "img.jpg").write_bytes(b"x")
        with self._src(tmp_path, monkeypatch).getmedia("img.jpg") as mf:
            assert mf.local_path.exists()


# ---------------------------------------------------------------------------
# FileMediaSource — harness + extras
# ---------------------------------------------------------------------------


class TestFileMediaSource(_LocalFsHarness):
    def _src(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> MediaSource:
        return FileMediaSource(path=str(root))

    def test_requires_absolute_path(self) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            FileMediaSource(path="relative/path")

    def test_uri_property(self) -> None:
        assert FileMediaSource(path="/data/media").uri == "file:///data/media"

    def test_scan_has_mtime(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "img.jpg").write_bytes(b"x")
        [mf] = list(self._src(tmp_path, monkeypatch).scan())
        assert mf.mtime is not None and mf.mtime > 0

    def test_scan_subfolder_missing_yields_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        files = list(self._src(tmp_path, monkeypatch).scan(subfolder="nonexistent"))
        assert files == []

    def test_getmedia_nested_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        nested = tmp_path / "2024"
        nested.mkdir()
        f = nested / "img.jpg"
        f.write_bytes(b"x")
        with self._src(tmp_path, monkeypatch).getmedia("2024/img.jpg") as mf:
            assert mf.local_path == f

    def test_getmedia_file_not_cleaned_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "img.jpg"
        f.write_bytes(b"x")
        with self._src(tmp_path, monkeypatch).getmedia("img.jpg"):
            pass
        assert f.exists()

    def test_getmedia_mtime_none_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mf = self._src(tmp_path, monkeypatch).getmedia("missing.jpg")
        assert mf.mtime is None

    def test_local_path_raises_outside_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "img.jpg").write_bytes(b"x")
        mf = self._src(tmp_path, monkeypatch).getmedia("img.jpg")
        with pytest.raises(RuntimeError, match="local_path"):
            _ = mf.local_path


# ---------------------------------------------------------------------------
# GdriveMediaSource — harness + extras
# ---------------------------------------------------------------------------


class TestGdriveMediaSource(_LocalFsHarness):
    def _src(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> MediaSource:
        _setup_colab_mock(monkeypatch)
        monkeypatch.setattr(GdriveMediaSource, "_MOUNT_POINT", root)
        return GdriveMediaSource()

    def test_uri_empty_path(self) -> None:
        assert GdriveMediaSource().uri == "gdrive:///"

    def test_uri_with_path(self) -> None:
        assert GdriveMediaSource("vacation/2024").uri == "gdrive:///vacation/2024"

    def test_scan_raises_outside_colab(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "google.colab", None)  # type: ignore[arg-type]
        with pytest.raises(ImportError, match="google-colab"):
            list(GdriveMediaSource().scan())

    def test_scan_mounts_drive(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mount_calls = _setup_colab_mock(monkeypatch)
        monkeypatch.setattr(GdriveMediaSource, "_MOUNT_POINT", tmp_path)
        list(GdriveMediaSource().scan())
        assert mount_calls == [("/content/drive", False)]

    def test_scan_uses_drive_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _setup_colab_mock(monkeypatch)
        monkeypatch.setattr(GdriveMediaSource, "_MOUNT_POINT", tmp_path)
        sub = tmp_path / "vacation"
        sub.mkdir()
        (sub / "beach.jpg").write_bytes(b"x")
        files = list(GdriveMediaSource("vacation").scan())
        assert len(files) == 1
        assert files[0].relative_path == "beach.jpg"


# ---------------------------------------------------------------------------
# RcloneMediaSource — tested separately (scan() requires _rclone_lsjson mock)
# ---------------------------------------------------------------------------


class TestRcloneMediaSource:
    def test_uri(self) -> None:
        assert RcloneMediaSource(remote="gdrive", path="photos").uri == "rclone:gdrive:///photos"

    def test_scheme_and_attrs(self) -> None:
        src = RcloneMediaSource(remote="backup", path="data")
        assert src.scheme == "rclone"
        assert src.remote == "backup"
        assert src.path == "data"

    def test_scan_yields_media_files(self) -> None:
        entries = [
            {"Path": "vacation.jpg", "IsDir": False, "ModTime": "2024-06-01T10:00:00Z"},
            {"Path": "notes.txt", "IsDir": False, "ModTime": "2024-06-01T10:00:00Z"},
            {"Path": "subdir", "IsDir": True},
        ]
        with patch("common.media._rclone_lsjson", return_value=entries):
            files = list(RcloneMediaSource(remote="gdrive", path="photos").scan())
        assert len(files) == 1
        assert files[0].relative_path == "vacation.jpg"
        assert files[0].media_type == "image"

    def test_scan_subfolder_prepends_prefix(self) -> None:
        entries = [{"Path": "img.jpg", "IsDir": False, "ModTime": "2024-01-01T00:00:00Z"}]
        with patch("common.media._rclone_lsjson", return_value=entries):
            files = list(RcloneMediaSource(remote="gdrive", path="photos").scan(subfolder="2024"))
        assert files[0].relative_path == "2024/img.jpg"

    def test_scan_skips_directories(self) -> None:
        entries = [
            {"Path": "dir", "IsDir": True},
            {"Path": "a.jpg", "IsDir": False, "ModTime": "2024-01-01T00:00:00Z"},
        ]
        with patch("common.media._rclone_lsjson", return_value=entries):
            files = list(RcloneMediaSource(remote="r", path="p").scan())
        assert len(files) == 1

    def test_scan_skips_unknown_extensions(self) -> None:
        entries = [{"Path": "doc.pdf", "IsDir": False, "ModTime": "2024-01-01T00:00:00Z"}]
        with patch("common.media._rclone_lsjson", return_value=entries):
            files = list(RcloneMediaSource(remote="r", path="p").scan())
        assert files == []

    def test_scan_mtime_parsed_from_iso(self) -> None:
        entries = [{"Path": "a.jpg", "IsDir": False, "ModTime": "2024-06-01T00:00:00Z"}]
        with patch("common.media._rclone_lsjson", return_value=entries):
            files = list(RcloneMediaSource(remote="r", path="p").scan())
        assert files[0].mtime is not None and files[0].mtime > 0

    def test_scan_mtime_none_when_missing(self) -> None:
        entries = [{"Path": "a.jpg", "IsDir": False}]
        with patch("common.media._rclone_lsjson", return_value=entries):
            files = list(RcloneMediaSource(remote="r", path="p").scan())
        assert files[0].mtime is None
