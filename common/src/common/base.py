"""StorePointer, IndexMeta, and resolve_instance — shared utilities."""

from __future__ import annotations

import importlib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDEX_META_FILE = "index_meta.json"
"""Filename of the index metadata sidecar written inside the DB directory."""

INDEXER_VERSION = "3.0.0"
"""Current indexer pipeline version.

Bumped from 2.0.0: ChromaCaptionIndexStore now stores data under
``db/captions/`` and face stores under ``db/faces/`` within the DB
directory.  IndexMeta gains an optional ``face_store`` field.
The indexer forces a full rebuild when the stored version differs from
this constant.
"""

# ---------------------------------------------------------------------------
# Shared URI-parsing base (private)
# ---------------------------------------------------------------------------


class _BasePointer:
    """Common fields and helpers shared by StorePointer."""

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
            path = rest[colon_pos + 1 :].lstrip("/")
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
        """Context manager that yields a local path to the named subdirectory."""
        local = self.get_dir(name)
        try:
            yield local
        finally:
            if self.scheme == "rclone":
                shutil.rmtree(local, ignore_errors=True)

    @contextmanager
    def get_file_ctx(self, relative_path: str) -> Generator[Path, None, None]:
        """Yield a local path to a single file at *relative_path* within this pointer's root."""
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


# ---------------------------------------------------------------------------
# IndexMeta — typed representation of index_meta.json
# ---------------------------------------------------------------------------


@dataclass
class IndexMeta:
    """Metadata written by the indexer and read by the search server.

    Stored as JSON at ``<db_dir>/index_meta.json``.
    """

    indexed_at: datetime
    source: str
    index_store: str
    """Dotted import path to the caption :class:`~common.index.IndexStore` implementation.

    Written by the indexer; read by the search server to resolve the right class.
    Example: ``"indexer.stores.chroma_caption.ChromaCaptionIndexStore"``
    """
    indexer_version: str = ""
    face_store: str | None = None
    """Optional dotted import path to the face :class:`~common.index.IndexStore` implementation.

    Present only when the indexer includes face detection and clustering.
    Example: ``"indexer.stores.chroma_face.ChromaFaceIndexStore"``
    """

    @staticmethod
    def load(path: Path) -> IndexMeta:
        """Load from a JSON file.

        Raises:
            FileNotFoundError: if the file does not exist.
            ValueError: if the file contains invalid JSON, is missing required
                fields, or was written by an older indexer version that used
                ``vectorizer`` / ``vector_store`` fields instead of
                ``index_store``.
        """
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON in {path}: {exc}") from exc

        # Detect old-format meta written before INDEXER_VERSION 2.0.0.
        if "index_store" not in data and ("vectorizer" in data or "vector_store" in data):
            raise ValueError(
                f"Index at {path} was built with an older version of the indexer "
                "(vectorizer/vector_store fields). Re-run the indexer to rebuild."
            )

        try:
            return IndexMeta(
                indexed_at=datetime.fromisoformat(data["indexed_at"]),
                source=data["source"],
                index_store=data["index_store"],
                indexer_version=data.get("indexer_version", ""),
                face_store=data.get("face_store"),
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Cannot parse field {exc} in {path}") from exc

    def save(self, path: Path) -> None:
        """Write to a JSON file, creating parent directories as needed."""
        path.parent.mkdir(parents=True, exist_ok=True)
        out = asdict(self)
        out["indexed_at"] = self.indexed_at.isoformat()
        if out.get("face_store") is None:
            out.pop("face_store", None)
        path.write_text(json.dumps(out, indent=2))

    @staticmethod
    def now(
        source: str,
        index_store: str,
        indexer_version: str = INDEXER_VERSION,
        face_store: str | None = None,
    ) -> IndexMeta:
        """Construct an :class:`IndexMeta` stamped with the current UTC time."""
        return IndexMeta(
            indexed_at=datetime.now(UTC),
            source=source,
            index_store=index_store,
            indexer_version=indexer_version,
            face_store=face_store,
        )


# ---------------------------------------------------------------------------
# resolve_instance — generic plugin loader
# ---------------------------------------------------------------------------


def resolve_instance(
    name: str,
    registry: dict[str, type[Any]],
    kind: str,
    expected_type: type[Any],
) -> Any:
    """Return an instance for *name*, looked up in *registry* or via dotted import.

    The resolved class must be a subclass of *expected_type*; otherwise a
    ``ValueError`` is raised.  This prevents index_meta.json from being used to
    instantiate arbitrary classes.

    Args:
        name: Short registry key (e.g. ``"chroma"``) or dotted import path
            (e.g. ``"indexer.stores.chroma_caption.ChromaCaptionIndexStore"``).
        registry: Mapping of short names to concrete types.
        kind: Human-readable label used in error messages (e.g. ``"index-store"``).
        expected_type: ABC or base class that the resolved class must implement.

    Returns:
        An instance of the resolved class.

    Raises:
        ValueError: if *name* cannot be resolved or the resolved class does not
            implement *expected_type*.
    """
    if name in registry:
        cls: type[Any] = registry[name]
    else:
        try:
            module_path, class_name = name.rsplit(".", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except Exception as exc:
            raise ValueError(f"Cannot load {kind} {name!r}: {exc}") from exc

    if not (isinstance(cls, type) and issubclass(cls, expected_type)):
        raise ValueError(
            f"{kind} {name!r} must be a subclass of {expected_type.__name__}, got {cls!r}"
        )
    return cls()
