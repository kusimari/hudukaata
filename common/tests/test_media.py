"""Tests for MediaFile, MediaSource, and FileMediaSource."""

from __future__ import annotations

from pathlib import Path

import pytest

from common.media import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    FileMediaSource,
    MediaFile,
    MediaSource,
)


class TestExtensionSets:
    def test_image_extensions_contain_jpg(self) -> None:
        assert ".jpg" in IMAGE_EXTENSIONS

    def test_video_extensions_contain_mp4(self) -> None:
        assert ".mp4" in VIDEO_EXTENSIONS

    def test_audio_extensions_contain_mp3(self) -> None:
        assert ".mp3" in AUDIO_EXTENSIONS


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


class TestFileMediaSourceScan:
    def test_scan_yields_image_files(self, tmp_path: Path) -> None:
        (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8\xff")
        (tmp_path / "readme.txt").write_text("not media")

        src = FileMediaSource(path=str(tmp_path))
        files = list(src.scan())

        assert len(files) == 1
        assert files[0].relative_path == "photo.jpg"
        assert files[0].media_type == "image"

    def test_scan_yields_video_files(self, tmp_path: Path) -> None:
        (tmp_path / "clip.mp4").write_bytes(b"ftyp")

        src = FileMediaSource(path=str(tmp_path))
        files = list(src.scan())

        assert len(files) == 1
        assert files[0].media_type == "video"

    def test_scan_yields_audio_files(self, tmp_path: Path) -> None:
        (tmp_path / "track.mp3").write_bytes(b"ID3")

        src = FileMediaSource(path=str(tmp_path))
        files = list(src.scan())

        assert len(files) == 1
        assert files[0].media_type == "audio"

    def test_scan_subfolder(self, tmp_path: Path) -> None:
        sub = tmp_path / "2024"
        sub.mkdir()
        (sub / "img.png").write_bytes(b"PNG")
        (tmp_path / "other.jpg").write_bytes(b"\xff\xd8\xff")

        src = FileMediaSource(path=str(tmp_path))
        files = list(src.scan(subfolder="2024"))

        assert len(files) == 1
        # relative_path is relative to root, not subfolder
        assert files[0].relative_path == "2024/img.png"

    def test_scan_subfolder_missing_yields_nothing(self, tmp_path: Path) -> None:
        src = FileMediaSource(path=str(tmp_path))
        files = list(src.scan(subfolder="nonexistent"))
        assert files == []

    def test_scan_relative_path_uses_root(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "img.jpg").write_bytes(b"\xff\xd8\xff")

        src = FileMediaSource(path=str(tmp_path))
        files = list(src.scan())

        assert files[0].relative_path == "a/b/img.jpg"

    def test_scan_file_has_mtime(self, tmp_path: Path) -> None:
        f = tmp_path / "img.jpg"
        f.write_bytes(b"\xff\xd8\xff")

        src = FileMediaSource(path=str(tmp_path))
        files = list(src.scan())

        assert files[0].mtime is not None
        assert files[0].mtime > 0

    def test_scan_mediafile_is_context_manager(self, tmp_path: Path) -> None:
        f = tmp_path / "img.jpg"
        f.write_bytes(b"\xff\xd8\xff")

        src = FileMediaSource(path=str(tmp_path))
        mf = list(src.scan())[0]

        with mf:
            assert mf.local_path == f

    def test_local_path_outside_context_raises(self, tmp_path: Path) -> None:
        (tmp_path / "img.jpg").write_bytes(b"\xff\xd8\xff")

        src = FileMediaSource(path=str(tmp_path))
        mf = list(src.scan())[0]

        with pytest.raises(RuntimeError, match="local_path"):
            _ = mf.local_path


class TestFileMediaSourceGetmedia:
    def test_getmedia_returns_mediafile(self, tmp_path: Path) -> None:
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8\xff")

        src = FileMediaSource(path=str(tmp_path))
        mf = src.getmedia("photo.jpg")

        assert isinstance(mf, MediaFile)
        assert mf.relative_path == "photo.jpg"
        assert mf.media_type == "image"

    def test_getmedia_context_manager(self, tmp_path: Path) -> None:
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8\xff")

        src = FileMediaSource(path=str(tmp_path))
        with src.getmedia("photo.jpg") as mf:
            assert mf.local_path == f

    def test_getmedia_nested_path(self, tmp_path: Path) -> None:
        nested = tmp_path / "2024"
        nested.mkdir()
        f = nested / "img.jpg"
        f.write_bytes(b"\xff\xd8\xff")

        src = FileMediaSource(path=str(tmp_path))
        with src.getmedia("2024/img.jpg") as mf:
            assert mf.local_path == f

    def test_getmedia_file_not_cleaned_up_on_exit(self, tmp_path: Path) -> None:
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8\xff")

        src = FileMediaSource(path=str(tmp_path))
        with src.getmedia("photo.jpg"):
            pass

        assert f.exists()

    def test_getmedia_has_mtime_when_file_exists(self, tmp_path: Path) -> None:
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8\xff")

        src = FileMediaSource(path=str(tmp_path))
        mf = src.getmedia("photo.jpg")

        assert mf.mtime is not None

    def test_getmedia_mtime_none_when_file_missing(self, tmp_path: Path) -> None:
        src = FileMediaSource(path=str(tmp_path))
        mf = src.getmedia("missing.jpg")

        assert mf.mtime is None


class TestFileMediaSourceUri:
    def test_uri_property(self) -> None:
        src = FileMediaSource(path="/data/media")
        assert src.uri == "file:///data/media"

    def test_requires_absolute_path(self) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            FileMediaSource(path="relative/path")
