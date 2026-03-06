"""MediaPointer and StorePointer — abstract file:// and rclone: URI schemes.

MediaPointer is for *reading* media files (iter_files, scan).
StorePointer is for *reading and writing* database directories (get_dir, put_dir, etc.).
Both share common URI parsing and rclone helpers via _BasePointer.

iter_files() yields ``(relative_path, file_ctx)`` pairs where *file_ctx* is a
context manager: ``with file_ctx as local_path:`` downloads the file (rclone) or
just returns the existing path (file://), and cleans up the temp dir on exit.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Generator, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
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
# MediaFile
# ---------------------------------------------------------------------------


@dataclass
class MediaFile:
    """A media file ready for captioning and vectorisation.

    ``local_path`` is always a valid, readable file on the local filesystem.

    **Lifetime contract (rclone sources):** when a ``MediaFile`` is produced by
    :meth:`MediaPointer.scan`, ``local_path`` is backed by a temporary directory
    that is deleted as soon as the caller's ``for`` loop advances to the next
    file.  Process ``local_path`` entirely within the current iteration — do not
    store references that outlive the loop body.  For ``file://`` sources the
    path is permanent and this restriction does not apply.
    """

    relative_path: str
    local_path: Path
    media_type: Literal["image", "video", "audio"]


# ---------------------------------------------------------------------------
# File context managers
# ---------------------------------------------------------------------------


class _LocalFile:
    """Context manager for local file:// paths — returns the path as-is, no cleanup."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def __enter__(self) -> Path:
        return self._path

    def __exit__(self, *args: object) -> None:
        pass  # local files are not managed by us


class _RcloneFile:
    """Context manager that downloads a single remote file on entry and deletes it on exit."""

    def __init__(self, pointer: _BasePointer, rel: str) -> None:
        self._pointer = pointer
        self._rel = rel
        self._tmpdir: Path | None = None

    def __enter__(self) -> Path:
        self._tmpdir = Path(tempfile.mkdtemp(prefix="indexer_rclone_"))
        local = self._tmpdir / self._rel
        local.parent.mkdir(parents=True, exist_ok=True)
        self._pointer._rclone_run(
            [
                "copyto",
                f"{self._pointer.remote}:{self._pointer.path}/{self._rel}",
                str(local),
            ]
        )
        return local

    def __exit__(self, *args: object) -> None:
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None


# ---------------------------------------------------------------------------
# Base pointer (shared URI parsing and rclone helpers)
# ---------------------------------------------------------------------------


@dataclass
class _BasePointer:
    scheme: Literal["file", "rclone"]
    remote: str | None  # rclone remote name; None for file://
    path: str  # absolute path (on FS or remote)

    @classmethod
    def parse(cls, uri: str) -> Self:
        """Parse a URI into a pointer instance.

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
            if not re.fullmatch(r"[A-Za-z0-9_-]+", remote):
                raise ValueError(
                    "rclone remote name must contain only alphanumerics, hyphens, or underscores"
                    f" (got {remote!r})"
                )
            path_part = rest[colon_pos + 1 :]
            path = path_part.lstrip("/")
            return cls(scheme="rclone", remote=remote, path=path)

        raise ValueError(f"Unsupported URI scheme: {uri!r}")

    @property
    def uri(self) -> str:
        """Reconstruct the URI string for this pointer."""
        if self.scheme == "file":
            return f"file://{self.path}"
        return f"rclone:{self.remote}:///{self.path}"

    def _rclone_lsjson(self) -> list[dict[str, Any]]:
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


@dataclass
class MediaPointer(_BasePointer):
    """Pointer to a media source directory. Supports read-only iteration."""

    def iter_files(self) -> Iterator[tuple[str, AbstractContextManager[Path]]]:
        """Yield ``(relative_path, file_ctx)`` for every file under this pointer.

        *file_ctx* is a context manager::

            for rel, file_ctx in pointer.iter_files():
                with file_ctx as local_path:
                    # local_path is valid here; cleaned up on with-block exit
                    process(rel, local_path)

        For ``file://`` pointers *file_ctx* is a no-op wrapper around the
        existing local path.  For ``rclone:`` pointers the file is downloaded
        inside the ``with`` block and the temp directory is deleted on exit,
        so large remotes never exhaust local disk.
        """
        if self.scheme == "file":
            root = Path(self.path)
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    yield str(p.relative_to(root)), _LocalFile(p)
        else:
            for entry in self._rclone_lsjson():
                if entry.get("IsDir"):
                    continue
                rel = entry["Path"]
                yield rel, _RcloneFile(self, rel)

    def scan(self) -> Iterator[MediaFile]:
        """Yield a :class:`MediaFile` for every recognised media file under this pointer.

        Files are yielded lazily, one at a time.  For ``rclone:`` sources each
        file is downloaded immediately before yielding and the local temp copy is
        deleted before the next file is fetched, so large remotes never exhaust
        local disk.

        **Important:** for rclone sources, ``MediaFile.local_path`` is only valid
        for the duration of a single loop iteration.  See :class:`MediaFile` for
        the full lifetime contract.
        """
        for relative_path, file_ctx in self.iter_files():
            ext = Path(relative_path).suffix.lower()
            media_type = _EXT_TO_TYPE.get(ext)
            if media_type is None:
                continue
            with file_ctx as local_path:
                yield MediaFile(
                    relative_path=relative_path,
                    local_path=local_path,
                    media_type=media_type,
                )


# ---------------------------------------------------------------------------
# StorePointer — read/write database storage
# ---------------------------------------------------------------------------


@dataclass
class StorePointer(_BasePointer):
    """Pointer to a store directory. Supports directory-level get/put/rename/delete."""

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
        """Download the directory at this pointer into a local temp dir.

        Returns the local temp dir path; caller must clean up.
        """
        if self.scheme == "file":
            return Path(self.path) / name if name else Path(self.path)
        tmpdir = Path(tempfile.mkdtemp(prefix="indexer_get_"))
        remote_path = f"{self.path}/{name}" if name else self.path
        self._rclone_run(["copy", f"{self.remote}:{remote_path}", str(tmpdir)])
        return tmpdir

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

    @contextmanager
    def get_dir_ctx(self, name: str | None = None) -> Generator[Path, None, None]:
        """Context manager that yields a local path to the named subdirectory.

        For ``file://`` pointers this is the directory itself (no copy, no
        cleanup).  For ``rclone:`` pointers the directory is downloaded into a
        temporary folder which is automatically deleted on context-manager exit,
        so callers never need to manage cleanup manually::

            with store.get_dir_ctx("db") as local_db:
                created_at = vector_store.created_at(local_db)
            # temp dir is gone here (rclone) or untouched (file://)
        """
        local = self.get_dir(name)
        try:
            yield local
        finally:
            if self.scheme == "rclone":
                shutil.rmtree(local, ignore_errors=True)
