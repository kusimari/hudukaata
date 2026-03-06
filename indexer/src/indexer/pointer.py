"""MediaPointer — abstracts file:// and rclone: URI schemes."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass
class MediaPointer:
    scheme: Literal["file", "rclone"]
    remote: str | None  # rclone remote name; None for file://
    path: str  # absolute path (on FS or remote)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse(uri: str) -> MediaPointer:
        """Parse a URI into a MediaPointer.

        Supported formats:
          file:///absolute/path
          rclone:remote-name:///path/on/remote
        """
        if uri.startswith("file://"):
            path = uri[len("file://") :]
            if not path.startswith("/"):
                raise ValueError(f"file:// URI must use an absolute path (got {uri!r})")
            return MediaPointer(scheme="file", remote=None, path=path)

        if uri.startswith("rclone:"):
            rest = uri[len("rclone:") :]
            # rest is  remote-name:///path  or  remote-name:/path
            try:
                colon_pos = rest.index(":")
            except ValueError:
                raise ValueError(
                    f"Invalid rclone URI (missing path separator after remote name): {uri!r}"
                ) from None
            remote = rest[:colon_pos]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", remote):
                raise ValueError(
                    f"rclone remote name must contain only alphanumerics, hyphens, or underscores"
                    f" (got {remote!r})"
                )
            path_part = rest[colon_pos + 1 :]
            # Strip leading slashes to get a clean remote path
            path = path_part.lstrip("/")
            return MediaPointer(scheme="rclone", remote=remote, path=path)

        raise ValueError(f"Unsupported URI scheme: {uri!r}")

    # ------------------------------------------------------------------
    # File iteration
    # ------------------------------------------------------------------

    def iter_files(self) -> Iterator[tuple[str, Path]]:
        """Yield (relative_path, local_path) for every file under this pointer."""
        if self.scheme == "file":
            root = Path(self.path)
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    yield str(p.relative_to(root)), p
        else:
            # List all files on the remote and download them to a temp dir.
            #
            # Lifetime contract: the downloaded files must remain accessible
            # until the caller has finished reading them. This generator uses
            # try/finally so the tmpdir is cleaned up when the generator is
            # closed (exhausted or garbage-collected). Callers that need the
            # files to outlive generator exhaustion (e.g. runner._run, which
            # calls list(scan(media)) and then processes files afterwards)
            # must exhaust this generator *after* processing, or refactor to
            # stream files one-at-a-time without collecting them first.
            entries = self._rclone_lsjson()
            tmpdir = Path(tempfile.mkdtemp(prefix="indexer_rclone_"))
            try:
                for entry in entries:
                    if entry.get("IsDir"):
                        continue
                    rel = entry["Path"]
                    local_dest = tmpdir / rel
                    local_dest.parent.mkdir(parents=True, exist_ok=True)
                    self._rclone_run(
                        [
                            "copyto",
                            f"{self.remote}:{self.path}/{rel}",
                            str(local_dest),
                        ]
                    )
                    yield rel, local_dest
            finally:
                import shutil

                shutil.rmtree(tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Directory operations
    # ------------------------------------------------------------------

    def put_dir(self, local_src: Path, dest_name: str | None = None) -> None:
        """Upload a local directory to this pointer location."""
        if self.scheme == "file":
            import shutil

            dest = Path(self.path) / (dest_name or local_src.name)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(local_src, dest)
        else:
            remote_dest = f"{self.path}/{dest_name or local_src.name}"
            self._rclone_run(
                [
                    "copy",
                    str(local_src),
                    f"{self.remote}:{remote_dest}",
                ]
            )

    def get_dir(self, name: str | None = None) -> Path:
        """Download the directory at this pointer into a local temp dir.

        Returns the local temp dir path; caller must clean up.
        """
        if self.scheme == "file":
            return Path(self.path) / name if name else Path(self.path)
        tmpdir = Path(tempfile.mkdtemp(prefix="indexer_get_"))
        remote_path = f"{self.path}/{name}" if name else self.path
        self._rclone_run(
            [
                "copy",
                f"{self.remote}:{remote_path}",
                str(tmpdir),
            ]
        )
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
            import shutil

            target = Path(self.path) / name
            if target.exists():
                shutil.rmtree(target)
        else:
            self._rclone_run(
                [
                    "purge",
                    f"{self.remote}:{self.path}/{name}",
                ]
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rclone_lsjson(self) -> list[dict[str, Any]]:
        result = self._rclone_run(
            [
                "lsjson",
                f"{self.remote}:{self.path}",
                "--recursive",
            ]
        )
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
