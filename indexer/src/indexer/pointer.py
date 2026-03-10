"""MediaPointer and StorePointer — abstract file:// and rclone: URI schemes.

MediaPointer is for *reading* media files (scan).
StorePointer is for *reading and writing* database directories (get_dir, put_dir, etc.).
Both share common URI parsing and rclone helpers via _BasePointer.

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

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Generator, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self

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
    ) -> None:
        self.relative_path = relative_path
        self.media_type = media_type
        self._ctx = _ctx
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
        return f"MediaFile({self.relative_path!r}, {self.media_type!r}, {state})"


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
# Base pointer (shared URI parsing and rclone helpers)
# ---------------------------------------------------------------------------


class _BasePointer:
    """Common fields and helpers shared by MediaPointer and StorePointer."""

    def __init__(
        self,
        scheme: Literal["file", "rclone"],
        remote: str | None,
        path: str,
    ) -> None:
        self.scheme = scheme
        self.remote = remote
        self.path = path

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.uri!r})"

    @classmethod
    def parse(cls, uri: str) -> Self:
        """Parse a URI string into a pointer instance.

        Supported formats::

          file:///absolute/path
          rclone:remote-name:///path/on/remote
        """
        if uri.startswith("file://"):
            path = uri[len("file://") :]
            if not path.startswith("/"):
                raise ValueError(f"file:// URI must use an absolute path (got {uri!r})")
            return cls(scheme="file", remote=None, path=path)

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
                    "rclone remote name must contain only alphanumerics, hyphens, underscores,"
                    f" or dots (got {remote!r})"
                )
            path_part = rest[colon_pos + 1 :]
            path = path_part.lstrip("/")
            return cls(scheme="rclone", remote=remote, path=path)

        raise ValueError(f"Unsupported URI scheme: {uri!r}")

    @property
    def uri(self) -> str:
        """Reconstruct the canonical URI string for this pointer."""
        if self.scheme == "file":
            return f"file://{self.path}"
        return f"rclone:{self.remote}:///{self.path}"

    def _rclone_lsjson(self) -> list[dict[str, Any]]:
        assert self.scheme == "rclone", "_rclone_lsjson() called on non-rclone pointer"
        result = self._rclone_run(["lsjson", f"{self.remote}:{self.path}", "--recursive"])
        data: list[dict[str, Any]] = json.loads(result.stdout or "[]")
        return data

    @staticmethod
    def _rclone_run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["rclone"] + args,
            capture_output=True,
            text=True,
            check=check,
        )


# ---------------------------------------------------------------------------
# MediaPointer — read-only media source
# ---------------------------------------------------------------------------


class MediaPointer(_BasePointer):
    """Pointer to a media source directory.  Supports read-only iteration via scan()."""

    def scan(self) -> Iterator[MediaFile]:
        """Yield a :class:`MediaFile` for every recognised media file under this pointer.

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
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    ext = p.suffix.lower()
                    media_type = _EXT_TO_TYPE.get(ext)
                    if media_type is None:
                        continue
                    yield MediaFile(
                        relative_path=str(p.relative_to(root)),
                        media_type=media_type,
                        _ctx=_LocalFile(p),
                    )
        else:
            with tempfile.TemporaryDirectory(prefix="indexer_scan_") as tmpdir_str:
                tmpdir = Path(tmpdir_str)
                for entry in self._rclone_lsjson():
                    if entry.get("IsDir"):
                        continue
                    rel = entry["Path"]
                    ext = Path(rel).suffix.lower()
                    media_type = _EXT_TO_TYPE.get(ext)
                    if media_type is None:
                        continue
                    yield MediaFile(
                        relative_path=rel,
                        media_type=media_type,
                        _ctx=_RcloneFile(self, rel, tmpdir),
                    )


# ---------------------------------------------------------------------------
# StorePointer — read/write database storage
# ---------------------------------------------------------------------------


class StorePointer(_BasePointer):
    """Pointer to a store directory.  Supports directory-level get/put/rename/delete."""

    def put_dir(self, local_src: Path, dest_name: str | None = None) -> None:
        """Upload a local directory to this pointer location."""
        if self.scheme == "file":
            dest = Path(self.path) / (dest_name or local_src.name)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(local_src, dest)
        else:
            remote_dest = f"{self.path}/{dest_name or local_src.name}"
            self._rclone_run(["copy", str(local_src), f"{self.remote}:{remote_dest}"])

    def get_dir(self, name: str | None = None) -> Path:
        """Return the local path to the named subdirectory.

        For ``file://`` sources this is the directory itself (no copy).
        For ``rclone:`` sources the directory is downloaded to a fresh temp dir;
        the caller is responsible for cleanup — prefer :meth:`get_dir_ctx`.
        """
        if self.scheme == "file":
            return Path(self.path) / name if name else Path(self.path)
        tmpdir = Path(tempfile.mkdtemp(prefix="indexer_get_"))
        remote_path = f"{self.path}/{name}" if name else self.path
        self._rclone_run(["copy", f"{self.remote}:{remote_path}", str(tmpdir)])
        return tmpdir

    @contextmanager
    def get_dir_ctx(self, name: str | None = None) -> Generator[Path, None, None]:
        """Context manager that yields a local path to the named subdirectory.

        For ``file://`` sources this is the directory itself (no copy, no
        cleanup).  For ``rclone:`` sources the directory is downloaded into a
        temporary folder which is automatically deleted on exit::

            with store.get_dir_ctx("db") as local_db:
                created_at = vector_store.created_at(local_db)
        """
        local = self.get_dir(name)
        try:
            yield local
        finally:
            if self.scheme == "rclone":
                shutil.rmtree(local, ignore_errors=True)

    def has_dir(self, name: str) -> bool:
        """Return True if a subdirectory with this name exists at the pointer location."""
        if self.scheme == "file":
            return (Path(self.path) / name).is_dir()
        try:
            result = self._rclone_run(
                ["lsjson", f"{self.remote}:{self.path}"],
                check=False,
            )
            entries = json.loads(result.stdout or "[]")
            return any(e.get("Name") == name and e.get("IsDir") for e in entries)
        except Exception:
            return False

    def rename_dir(self, old: str, new: str) -> None:
        """Rename a subdirectory at this location."""
        if self.scheme == "file":
            root = Path(self.path)
            (root / old).rename(root / new)
        else:
            self._rclone_run(
                [
                    "moveto",
                    f"{self.remote}:{self.path}/{old}",
                    f"{self.remote}:{self.path}/{new}",
                ]
            )

    def delete_dir(self, name: str) -> None:
        """Delete a subdirectory at this location."""
        if self.scheme == "file":
            target = Path(self.path) / name
            if target.exists():
                shutil.rmtree(target)
        else:
            self._rclone_run(["purge", f"{self.remote}:{self.path}/{name}"])
