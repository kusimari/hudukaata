"""MediaPointer — abstract file:// and rclone: URI schemes for media scanning.

MediaPointer is for *reading* media files (scan).
StorePointer (for reading/writing the index store) lives in common.pointer.

scan() yields MediaFile objects that are context managers.  Use each one with a
``with`` block to access the file on disk::

    for mf in media.scan():
        with mf:
            process(mf.local_path)  # valid here; cleaned up on exit for rclone

For rclone sources a single shared temporary directory is created per scan() call;
each file is downloaded into it on context entry and deleted on exit, so large
remotes never exhaust local disk.
"""

from __future__ import annotations

import contextlib
import logging
import tempfile
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Literal

# StorePointer and its base live in common — re-exported so existing callers
# that imported StorePointer from indexer.pointer continue to work.
from common.pointer import StorePointer as StorePointer
from common.pointer import _BasePointer

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
    """A media file yielded by :meth:`MediaPointer.scan`.

    Use as a context manager to access the file on disk::

        for mf in media.scan():
            with mf:
                caption = model.caption(mf)   # mf.local_path is valid here

    ``local_path`` raises :class:`RuntimeError` if accessed outside the
    ``with`` block.  For ``file://`` sources the underlying path is permanent;
    the context entry/exit are no-ops.  For ``rclone:`` sources the file is
    downloaded on ``__enter__`` and deleted on ``__exit__``.
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
                "Use: for mf in media.scan(): with mf: ..."
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

    def __init__(self, pointer: _BasePointer, rel: str, tmpdir: Path) -> None:
        self._pointer = pointer
        self._rel = rel
        self._tmpdir = tmpdir
        self._local: Path | None = None

    def __enter__(self) -> Path:
        local = self._tmpdir / self._rel
        local.parent.mkdir(parents=True, exist_ok=True)
        self._pointer._rclone_run(
            [
                "copyto",
                f"{self._pointer.remote}:{self._pointer.path}/{self._rel}",
                str(local),
            ]
        )
        self._local = local
        return local

    def __exit__(self, *args: object) -> None:
        if self._local is not None:
            self._local.unlink(missing_ok=True)
            self._local = None


# ---------------------------------------------------------------------------
# MediaPointer — read-only media source
# ---------------------------------------------------------------------------


class MediaPointer(_BasePointer):
    """Pointer to a media source directory.  Supports read-only iteration via scan()."""

    def scan(self, subfolder: str | None = None) -> Iterator[MediaFile]:
        """Yield a :class:`MediaFile` for every recognised media file under this pointer.

        Args:
            subfolder: Optional path relative to this pointer's root.  When
                given, only files under that subfolder are yielded.
                ``relative_path`` on each :class:`MediaFile` is still relative
                to the *original* root (e.g. ``"2024/vacation.jpg"``), not to
                the subfolder itself, so paths are consistent across runs that
                target different subfolders of the same store.

        Each :class:`MediaFile` is a context manager.  Use it with ``with``::

            for mf in media.scan():
                with mf:
                    process(mf.local_path)

        For ``file://`` sources the context entry/exit are no-ops and the path
        is always valid.  For ``rclone:`` sources a single shared temporary
        directory is created for the duration of the scan; each file is
        downloaded on context entry and its local copy is deleted on exit,
        keeping disk usage bounded to at most one file at a time.
        """
        if self.scheme == "file":
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
        else:
            # For rclone, concatenate the subfolder into the remote path so
            # the lsjson call only retrieves the targeted subtree.
            if subfolder:
                sub_path = f"{self.path}/{subfolder.strip('/')}"
                prefix = subfolder.strip("/") + "/"
            else:
                sub_path = self.path
                prefix = ""
            # Build a temporary pointer aimed at sub_path to reuse _rclone_lsjson.
            sub_pointer = self.__class__(scheme="rclone", remote=self.remote, path=sub_path)
            with tempfile.TemporaryDirectory(prefix="indexer_scan_") as tmpdir_str:
                tmpdir = Path(tmpdir_str)
                for entry in sub_pointer._rclone_lsjson():
                    if entry.get("IsDir"):
                        continue
                    # entry["Path"] is relative to sub_path; prepend the
                    # subfolder prefix to make it relative to the original root.
                    rel = prefix + entry["Path"] if prefix else entry["Path"]
                    ext = Path(rel).suffix.lower()
                    media_type = _EXT_TO_TYPE.get(ext)
                    if media_type is None:
                        continue
                    mtime: float | None = None
                    raw_mtime = entry.get("ModTime")
                    if raw_mtime:
                        with contextlib.suppress(ValueError):
                            mtime = datetime.fromisoformat(
                                raw_mtime.replace("Z", "+00:00")
                            ).timestamp()
                    yield MediaFile(
                        relative_path=rel,
                        media_type=media_type,
                        _ctx=_RcloneFile(self, rel, tmpdir),
                        mtime=mtime,
                    )
