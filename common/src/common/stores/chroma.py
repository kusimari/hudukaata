"""ChromaDB vector store (default implementation)."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.stores.base import VectorStore

_META_FILE = "db_meta.json"


class ChromaVectorStore(VectorStore):
    def __init__(self, collection_name: str = "media") -> None:
        self.collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None
        # Temp directory used by create_empty() / load_for_update(); moved to
        # final path in save().
        self._tmp_dir: Path | None = None
        # Preserved creation timestamp from an existing DB loaded via
        # load_for_update().  Written into db_meta.json by save() so that
        # archive names reflect when the DB was first created, not updated.
        self._created_at: datetime | None = None
        # Lazy cache populated on the first get_metadata() call.
        self._meta_cache: dict[str, dict[str, str]] | None = None

    # ------------------------------------------------------------------
    # VectorStore interface
    # ------------------------------------------------------------------

    def load(self, local_path: Path) -> None:
        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.PersistentClient(
            path=str(local_path),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_collection(self.collection_name)

    def load_for_update(self, local_path: Path) -> None:
        """Copy *local_path* to a temp dir and open it for read-write.

        The original DB at *local_path* is untouched.  After this call the
        store behaves like it was initialised via :meth:`create_empty` and
        supports :meth:`upsert`, :meth:`checkpoint`, and :meth:`save`.
        """
        import chromadb
        from chromadb.config import Settings

        tmp_dir = Path(tempfile.mkdtemp(prefix="chroma_upd_"))
        try:
            shutil.copytree(str(local_path), str(tmp_dir), dirs_exist_ok=True)
            client = chromadb.PersistentClient(
                path=str(tmp_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            collection = client.get_collection(self.collection_name)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        self._tmp_dir = tmp_dir
        self._client = client
        self._collection = collection
        self._created_at = self.created_at(local_path)
        self._meta_cache = None

    def create_empty(self) -> None:
        import chromadb
        from chromadb.config import Settings

        # Use a PersistentClient in a temp dir so data is on disk and can be
        # moved atomically to the final location in save().
        tmp_dir = Path(tempfile.mkdtemp(prefix="chroma_"))
        try:
            client = chromadb.PersistentClient(
                path=str(tmp_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            collection = client.create_collection(self.collection_name)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        self._tmp_dir = tmp_dir
        self._client = client
        self._collection = collection
        self._created_at = None
        self._meta_cache = None

    def add(
        self,
        id: str,
        vector: list[float],
        metadata: dict[str, str],
    ) -> None:
        if self._collection is None:
            raise RuntimeError("Store not initialised; call load() or create_empty() first")
        self._collection.add(
            ids=[id],
            embeddings=[vector],
            metadatas=[metadata],
        )

    def upsert(
        self,
        id: str,
        vector: list[float],
        metadata: dict[str, str],
    ) -> None:
        if self._collection is None:
            raise RuntimeError(
                "Store not initialised; call load_for_update() or create_empty() first"
            )
        self._collection.upsert(
            ids=[id],
            embeddings=[vector],
            metadatas=[metadata],
        )
        # Invalidate cache so a subsequent get_metadata() reflects the change.
        if self._meta_cache is not None:
            self._meta_cache[id] = metadata

    def get_metadata(self, id: str) -> dict[str, str] | None:
        if self._collection is None:
            raise RuntimeError(
                "Store not initialised; call load_for_update() or create_empty() first"
            )
        if self._meta_cache is None:
            result = self._collection.get(include=["metadatas"])
            self._meta_cache = {
                doc_id: meta
                for doc_id, meta in zip(result["ids"], result["metadatas"], strict=True)
            }
        return self._meta_cache.get(id)

    def checkpoint(self, local_path: Path) -> None:
        if self._tmp_dir is None:
            raise RuntimeError(
                "checkpoint() requires the store to be initialised via"
                " create_empty() or load_for_update()"
            )
        if local_path.exists():
            shutil.rmtree(local_path)
        shutil.copytree(str(self._tmp_dir), str(local_path))

    def save(self, local_path: Path) -> None:
        if self._tmp_dir is None:
            # _tmp_dir is only set by create_empty() / load_for_update().
            raise RuntimeError(
                "save() requires the store to have been initialised via create_empty() "
                "or load_for_update(). load() is for read queries only and does not "
                "support re-saving."
            )
        # Release client/collection handles before moving the directory.
        # ChromaDB's PersistentClient may hold open file handles; closing them
        # first avoids failures on Windows and certain Linux configurations.
        self._client = None
        self._collection = None
        self._meta_cache = None
        # Write sidecar into the temp dir BEFORE the move so it travels
        # atomically with the rest of the DB contents.  A crash after the move
        # but before a post-move write would leave a valid DB with no timestamp.
        tmp_dir = self._tmp_dir
        self._tmp_dir = None
        # Use the preserved creation time for update runs so that archive names
        # reflect when the DB was first built, not when it was last updated.
        created_ts = (self._created_at or datetime.now(UTC)).isoformat()
        self._created_at = None
        # Write sidecar and move are inside the same try block so a write_text
        # failure also triggers cleanup of the orphaned temp directory.
        try:
            meta = {"created_at": created_ts}
            (tmp_dir / _META_FILE).write_text(json.dumps(meta))
            # PersistentClient auto-persists on write; just move the directory.
            if local_path.exists():
                shutil.rmtree(local_path)
            shutil.move(str(tmp_dir), str(local_path))
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def query(
        self,
        vector: list[float],
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Return up to *n_results* documents closest to *vector*."""
        if self._collection is None:
            raise RuntimeError("Store not initialised; call load() or create_empty() first")
        # ChromaDB raises an error when n_results exceeds the collection size,
        # so clamp to the actual count.  An empty collection returns [].
        effective_n = min(n_results, self._collection.count())
        if effective_n == 0:
            return []
        results = self._collection.query(
            query_embeddings=[vector],
            n_results=effective_n,
            include=["metadatas"],
        )
        return [
            {"id": id_, **meta}
            for id_, meta in zip(results["ids"][0], results["metadatas"][0], strict=True)
        ]

    def created_at(self, local_path: Path) -> datetime | None:
        meta_path = local_path / _META_FILE
        if not meta_path.exists():
            return None
        try:
            data = json.loads(meta_path.read_text())
            return datetime.fromisoformat(data["created_at"])
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
