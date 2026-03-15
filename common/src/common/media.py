"""MediaSource — abstract interface and concrete implementations for media access.

All concrete types implement the :class:`MediaSource` ABC, which exposes
``uri``, ``scan()``, and ``getmedia()``.

Concrete implementations:

* :class:`FileMediaSource` — local ``file://`` filesystem.
* :class:`RcloneMediaSource` — remote ``rclone:`` source.
* :class:`GdriveMediaSource` — Google Drive mounted inside Google Colab.

Use :meth:`MediaSource.from_uri` to construct the right implementation from a
URI string.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Media type constants
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".tiff",
    ".heic",
    ".heif",
    ".avif",
}
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
}
AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".aac",
    ".ogg",
    ".m4a",
    ".opus",
    ".wma",
}

_EXT_TO_TYPE: dict[str, Literal["image", "video", "audio"]] = {
    **{ext: "image" for ext in IMAGE_EXTENSIONS},
    **{ext: "video" for ext in VIDEO_EXTENSIONS},
    **{ext: "audio" for ext in AUDIO_EXTENSIONS},
}


# ---------------------------------------------------------------------------
# MediaFile — context-manager wrapper around a single media file
# ---------------------------------------------------------------------------


class MediaFile:
    """A media file yielded by :meth:`MediaSource.scan` or returned by
    :meth:`MediaSource.getmedia`.

    Use as a context manager to access the file on disk::

        for mf in source.scan():
            with mf:
                caption = model.caption(mf)   # mf.local_path is valid here

    ``local_path`` raises :class:`RuntimeError` if accessed outside the
    ``with`` block.  For ``file://`` sources the context entry/exit are no-ops.
    For ``rclone:`` sources the file is downloaded on ``__enter__`` and deleted
    on ``__exit__``.
    """

    def __init__(
        self,
        relative_path: str,
        media_type: Literal["image", "video", "audio"],
        _ctx: AbstractContextManager[Path],
        mtime: float | None = None,
    ) -> None:
        self.relative_path = relative_path
        self.media_type = media_type
        self._ctx = _ctx
        self.mtime = mtime
        """UTC modification timestamp (seconds since epoch), or ``None`` if unavailable."""
        self._local: Path | None = None

    @property
    def local_path(self) -> Path:
        """Local filesystem path to the file.  Only valid inside ``with mf:``."""
        if self._local is None:
            raise RuntimeError(
                "local_path is only accessible inside a 'with mf:' block. "
                "Use: for mf in source.scan(): with mf: ..."
            )
        return self._local

    def __enter__(self) -> MediaFile:
        self._local = self._ctx.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._ctx.__exit__(exc_type, exc_val, exc_tb)
        self._local = None

    def __repr__(self) -> str:
        state = "open" if self._local is not None else "closed"
        return (
            f"MediaFile({self.relative_path!r}, {self.media_type!r}, mtime={self.mtime}, {state})"
        )


# ---------------------------------------------------------------------------
# Internal file-context implementations
# ---------------------------------------------------------------------------


class _LocalFile:
    """Context manager for a pre-existing local path — no download, no cleanup."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def __enter__(self) -> Path:
        return self._path

    def __exit__(self, *args: object) -> None:
        pass


class _RcloneFile:
    """Context manager that downloads one remote file and deletes it on exit.

    The *tmpdir* is shared across all files in a single scan() call; this class
    only deletes its own file, never the directory.
    """

    def __init__(self, remote: str, path: str, rel: str, tmpdir: Path) -> None:
        self._remote = remote
        self._path = path
        self._rel = rel
        self._tmpdir = tmpdir
        self._local: Path | None = None

    def __enter__(self) -> Path:
        local = self._tmpdir / self._rel
        local.parent.mkdir(parents=True, exist_ok=True)
        _rclone_run(["copyto", f"{self._remote}:{self._path}/{self._rel}", str(local)])
        self._local = local
        return local

    def __exit__(self, *args: object) -> None:
        if self._local is not None:
            self._local.unlink(missing_ok=True)
            self._local = None


class _RcloneGetFile:
    """Context manager that downloads one file to a private tmpdir.

    Unlike :class:`_RcloneFile`, this class owns its tmpdir and removes it on
    exit.  Used by :meth:`RcloneMediaSource.getmedia` for single-file access.
    """

    def __init__(self, remote: str, path: str, rel: str) -> None:
        self._remote = remote
        self._path = path
        self._rel = rel
        self._tmpdir: Path | None = None

    def __enter__(self) -> Path:
        self._tmpdir = Path(tempfile.mkdtemp(prefix="media_get_"))
        local = self._tmpdir / Path(self._rel).name
        local.parent.mkdir(parents=True, exist_ok=True)
        _rclone_run(["copyto", f"{self._remote}:{self._path}/{self._rel}", str(local)])
        return local

    def __exit__(self, *args: object) -> None:
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None


# ---------------------------------------------------------------------------
# Rclone subprocess helpers — module-level so all implementations share them
# ---------------------------------------------------------------------------


def _rclone_run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["rclone"] + args,
        capture_output=True,
        text=True,
        check=check,
    )


def _rclone_lsjson(remote: str, path: str) -> list[dict[str, Any]]:
    result = _rclone_run(["lsjson", f"{remote}:{path}", "--recursive"])
    data: list[dict[str, Any]] = json.loads(result.stdout or "[]")
    return data


# ---------------------------------------------------------------------------
# MediaSource — abstract interface
# ---------------------------------------------------------------------------


class MediaSource(ABC):
    """Abstract media source — yields :class:`MediaFile` instances via :meth:`scan`
    and fetches individual files via :meth:`getmedia`.

    Linkage contract: ``MediaFile.relative_path`` returned by :meth:`scan` equals
    ``IndexResult.relative_path`` returned by an IndexStore.  Pass one directly
    to :meth:`getmedia` — no translation needed.
    """

    @property
    @abstractmethod
    def uri(self) -> str:
        """Canonical URI string identifying this source."""

    @abstractmethod
    def scan(self, subfolder: str | None = None) -> Iterator[MediaFile]:
        """Yield a :class:`MediaFile` for every recognised media file.

        Args:
            subfolder: Optional path relative to this source's root.  When
                given, only files under that subtree are yielded.
                ``relative_path`` on each :class:`MediaFile` is always relative
                to the *original* root, not the subfolder.
        """

    @abstractmethod
    def getmedia(self, relative_path: str) -> MediaFile:
        """Return a :class:`MediaFile` for a known *relative_path* without scanning.

        Use as a context manager to access the local file::

            with source.getmedia("2024/sunset.jpg") as mf:
                data = mf.local_path.read_bytes()

        For ``file://`` sources the context entry/exit are no-ops.
        For ``rclone:`` sources the file is downloaded on ``__enter__`` and the
        temp directory is removed on ``__exit__``.
        """

    @classmethod
    def from_uri(cls, uri: str) -> MediaSource:
        """Factory: construct the right :class:`MediaSource` from a URI string.

        Supported formats::

          file:///absolute/path       → FileMediaSource
          rclone:remote-name:///path  → RcloneMediaSource
          gdrive:///optional/path     → GdriveMediaSource

        Raises:
            ValueError: on unknown scheme or invalid URI format.
        """
        if uri.startswith("file://"):
            path = uri[len("file://") :]
            if not path.startswith("/"):
                raise ValueError(f"file:// URI must use an absolute path (got {uri!r})")
            return FileMediaSource(path=path)

        if uri.startswith("rclone:"):
            rest = uri[len("rclone:") :]
            try:
                colon_pos = rest.index(":")
            except ValueError:
                raise ValueError(
                    f"Invalid rclone URI (missing path separator after remote name): {uri!r}"
                ) from None
            remote = rest[:colon_pos]
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
                raise ValueError(
                    "rclone remote name must contain only alphanumerics, hyphens,"
                    f" underscores, or dots (got {remote!r})"
                )
            path = rest[colon_pos + 1 :].lstrip("/")
            return RcloneMediaSource(remote=remote, path=path)

        if uri.startswith("gdrive:"):
            drive_path = uri[len("gdrive:///") :]
            return GdriveMediaSource(drive_path=drive_path)

        raise ValueError(f"Unsupported URI scheme: {uri!r}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.uri!r})"


# ---------------------------------------------------------------------------
# FileMediaSource — local filesystem
# ---------------------------------------------------------------------------


class FileMediaSource(MediaSource):
    """MediaSource backed by a local filesystem directory."""

    scheme: Literal["file"] = "file"
    remote: None = None

    def __init__(self, path: str) -> None:
        if not path.startswith("/"):
            raise ValueError(
                f"FileMediaSource requires an absolute path (got {path!r}). "
                "Use file:///absolute/path URI format."
            )
        self.path = path

    @property
    def uri(self) -> str:
        return f"file://{self.path}"

    def scan(self, subfolder: str | None = None) -> Iterator[MediaFile]:
        root = Path(self.path)
        scan_root = root / subfolder if subfolder else root
        if not scan_root.is_dir():
            logger.warning(
                "Subfolder %r does not exist under %s — nothing to scan.", subfolder, root
            )
            return
        for p in sorted(scan_root.rglob("*")):
            if p.is_file():
                ext = p.suffix.lower()
                media_type = _EXT_TO_TYPE.get(ext)
                if media_type is None:
                    continue
                yield MediaFile(
                    relative_path=str(p.relative_to(root)),
                    media_type=media_type,
                    _ctx=_LocalFile(p),
                    mtime=p.stat().st_mtime,
                )

    def getmedia(self, relative_path: str) -> MediaFile:
        p = Path(self.path) / relative_path
        ext = p.suffix.lower()
        media_type = _EXT_TO_TYPE.get(ext, "image")
        mtime: float | None = None
        if p.exists():
            mtime = p.stat().st_mtime
        return MediaFile(
            relative_path=relative_path,
            media_type=media_type,
            _ctx=_LocalFile(p),
            mtime=mtime,
        )


# ---------------------------------------------------------------------------
# RcloneMediaSource — rclone remote
# ---------------------------------------------------------------------------


class RcloneMediaSource(MediaSource):
    """MediaSource backed by an rclone remote."""

    scheme: Literal["rclone"] = "rclone"

    def __init__(self, remote: str, path: str) -> None:
        self.remote = remote
        self.path = path

    @property
    def uri(self) -> str:
        return f"rclone:{self.remote}:///{self.path}"

    def scan(self, subfolder: str | None = None) -> Iterator[MediaFile]:
        if subfolder:
            sub_path = f"{self.path}/{subfolder.strip('/')}"
            prefix = subfolder.strip("/") + "/"
        else:
            sub_path = self.path
            prefix = ""
        with tempfile.TemporaryDirectory(prefix="media_scan_") as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            for entry in _rclone_lsjson(self.remote, sub_path):
                if entry.get("IsDir"):
                    continue
                rel = prefix + entry["Path"] if prefix else entry["Path"]
                ext = Path(rel).suffix.lower()
                media_type = _EXT_TO_TYPE.get(ext)
                if media_type is None:
                    continue
                mtime: float | None = None
                raw_mtime = entry.get("ModTime")
                if raw_mtime:
                    with contextlib.suppress(ValueError):
                        mtime = datetime.fromisoformat(raw_mtime.replace("Z", "+00:00")).timestamp()
                yield MediaFile(
                    relative_path=rel,
                    media_type=media_type,
                    _ctx=_RcloneFile(self.remote, self.path, rel, tmpdir),
                    mtime=mtime,
                )

    def getmedia(self, relative_path: str) -> MediaFile:
        ext = Path(relative_path).suffix.lower()
        media_type = _EXT_TO_TYPE.get(ext, "image")
        return MediaFile(
            relative_path=relative_path,
            media_type=media_type,
            _ctx=_RcloneGetFile(self.remote, self.path, relative_path),
        )


# ---------------------------------------------------------------------------
# GdriveMediaSource — Google Drive in Google Colab
# ---------------------------------------------------------------------------


class GdriveMediaSource(MediaSource):
    """MediaSource that reads from a Google Drive mounted inside Google Colab.

    Raises :class:`ImportError` when used outside Google Colab.
    """

    _MOUNT_POINT: Path = Path("/content/drive/MyDrive")

    def __init__(self, drive_path: str = "") -> None:
        self.drive_path = drive_path.strip("/")

    @property
    def uri(self) -> str:
        if self.drive_path:
            return f"gdrive:///{self.drive_path}"
        return "gdrive:///"

    def _mount(self) -> None:
        try:
            from google.colab import drive as _colab_drive
        except ImportError as exc:
            raise ImportError(
                "google-colab is not available. "
                "GdriveMediaSource can only be used inside Google Colab."
            ) from exc
        _colab_drive.mount("/content/drive", force_remount=False)

    def _root(self) -> Path:
        return self._MOUNT_POINT / self.drive_path if self.drive_path else self._MOUNT_POINT

    def scan(self, subfolder: str | None = None) -> Iterator[MediaFile]:
        self._mount()
        root = self._root()
        scan_root = root / subfolder if subfolder else root
        if not scan_root.is_dir():
            logger.warning(
                "Subfolder %r does not exist under %s — nothing to scan.", subfolder, root
            )
            return
        for p in sorted(scan_root.rglob("*")):
            if p.is_file():
                ext = p.suffix.lower()
                media_type = _EXT_TO_TYPE.get(ext)
                if media_type is None:
                    continue
                yield MediaFile(
                    relative_path=str(p.relative_to(root)),
                    media_type=media_type,
                    _ctx=_LocalFile(p),
                    mtime=p.stat().st_mtime,
                )

    def getmedia(self, relative_path: str) -> MediaFile:
        self._mount()
        root = self._root()
        p = root / relative_path
        ext = p.suffix.lower()
        media_type = _EXT_TO_TYPE.get(ext, "image")
        mtime: float | None = None
        if p.exists():
            mtime = p.stat().st_mtime
        return MediaFile(
            relative_path=relative_path,
            media_type=media_type,
            _ctx=_LocalFile(p),
            mtime=mtime,
        )
