"""StorePointer — abstract file:// and rclone: URI schemes for read/write store access.

StorePointer is for *reading and writing* database directories (get_dir, put_dir, etc.).

Usage::

    store = StorePointer.parse("file:///data/mystore")
    with store.get_dir_ctx("db") as db_path:
        # db_path is a local Path; cleaned up on exit for rclone sources
        process(db_path)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Self

# ---------------------------------------------------------------------------
# Shared base (URI parsing + rclone helpers)
# ---------------------------------------------------------------------------


class _BasePointer:
    """Common fields and helpers shared by StorePointer (and MediaPointer in indexer)."""

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
            # rclone remote paths are always relative to the remote root, so we
            # strip all leading slashes to produce a canonical form.  The uri
            # property always rebuilds as rclone:remote:///path, so the round-
            # trip is stable regardless of how many slashes the caller supplied.
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
        if self.scheme != "rclone":
            raise RuntimeError(
                f"_rclone_lsjson() called on non-rclone pointer (scheme={self.scheme!r})"
            )
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
        tmpdir = Path(tempfile.mkdtemp(prefix="store_get_"))
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

    @contextmanager
    def get_file_ctx(self, relative_path: str) -> Generator[Path, None, None]:
        """Yield a local path to a single file at *relative_path* within this pointer's root.

        For ``file://`` sources the path is returned directly — no copy, no cleanup.
        For ``rclone:`` sources the file is downloaded to a temporary directory,
        yielded, and the directory is removed on exit::

            with pointer.get_file_ctx("photos/sunset.jpg") as local:
                data = local.read_bytes()
        """
        if self.scheme == "file":
            yield Path(self.path) / relative_path
        else:
            tmpdir = Path(tempfile.mkdtemp(prefix="store_file_"))
            local = tmpdir / Path(relative_path).name
            try:
                self._rclone_run(
                    [
                        "copyto",
                        f"{self.remote}:{self.path}/{relative_path}",
                        str(local),
                    ]
                )
                yield local
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

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
        except (subprocess.CalledProcessError, json.JSONDecodeError):
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
