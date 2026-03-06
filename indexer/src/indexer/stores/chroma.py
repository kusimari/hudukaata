"""ChromaDB vector store (default implementation)."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from indexer.stores.base import VectorStore

_META_FILE = "db_meta.json"


class ChromaVectorStore(VectorStore):
    def __init__(self, collection_name: str = "media") -> None:
        self.collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None
        # Temp directory used by create_empty(); moved to final path in save().
        self._tmp_dir: Path | None = None

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
        self._collection = self._client.get_or_create_collection(self.collection_name)

    def create_empty(self) -> None:
        import chromadb
        from chromadb.config import Settings

        # Use a PersistentClient in a temp dir so data is on disk and can be
        # moved atomically to the final location in save().
        tmp_dir = Path(tempfile.mkdtemp(prefix="indexer_chroma_"))
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

    def save(self, local_path: Path) -> None:
        if self._client is None or self._tmp_dir is None:
            raise RuntimeError("Store not initialised; call create_empty() before save()")
        # PersistentClient auto-persists on write; just move the directory.
        if local_path.exists():
            shutil.rmtree(local_path)
        shutil.move(str(self._tmp_dir), str(local_path))
        self._tmp_dir = None

        # Write sidecar metadata
        meta = {"created_at": datetime.now(UTC).isoformat()}
        (local_path / _META_FILE).write_text(json.dumps(meta))

    def created_at(self, local_path: Path) -> datetime | None:
        meta_path = local_path / _META_FILE
        if not meta_path.exists():
            return None
        try:
            data = json.loads(meta_path.read_text())
            return datetime.fromisoformat(data["created_at"])
        except Exception:
            return None
