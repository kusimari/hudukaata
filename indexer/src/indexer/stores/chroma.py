"""ChromaDB vector store (default implementation)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from indexer.stores.base import VectorStore

_META_FILE = "db_meta.json"


class ChromaVectorStore(VectorStore):
    def __init__(self, collection_name: str = "media") -> None:
        self.collection_name = collection_name
        self._client = None
        self._collection = None

    # ------------------------------------------------------------------
    # VectorStore interface
    # ------------------------------------------------------------------

    def load(self, local_path: Path) -> None:
        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.Client(
            Settings(
                chroma_db_impl="duckdb+parquet",
                persist_directory=str(local_path),
                anonymized_telemetry=False,
            )
        )
        self._collection = self._client.get_or_create_collection(self.collection_name)

    def create_empty(self) -> None:
        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.Client(
            Settings(
                chroma_db_impl="duckdb+parquet",
                persist_directory=None,
                anonymized_telemetry=False,
            )
        )
        self._collection = self._client.create_collection(self.collection_name)

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
        if self._client is None:
            raise RuntimeError("Store not initialised")
        local_path.mkdir(parents=True, exist_ok=True)
        self._client.persist()

        # Write sidecar metadata
        meta = {"created_at": datetime.now(timezone.utc).isoformat()}
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
