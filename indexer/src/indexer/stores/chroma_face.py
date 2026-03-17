"""ChromaFaceIndexStore — ChromaDB implementation of IndexStore[FaceItem].

Stores face cluster centroids as ChromaDB vectors.  Data lives under
``<db_path>/faces/`` so that caption and face stores can share the same
``db_path`` root.

:meth:`list_all` returns clusters sorted by frequency (count) — used by the
``GET /faces`` endpoint to populate the face ribbon.
:meth:`search` finds the nearest clusters to a query face embedding — used
for face-similarity lookup.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.index import FaceItem, IndexResult, IndexStore

_META_FILE = "db_meta.json"
_COLLECTION_NAME = "faces"
_SUB_DIR = "faces"


class ChromaFaceIndexStore(IndexStore[FaceItem]):
    """Face cluster store: SentenceTransformer-dimension-free, vector-direct storage.

    Each document is a face cluster identified by a UUID *cluster_id*.
    The stored vector is the cluster centroid.  Metadata records:
    - ``count`` — number of face detections assigned to this cluster
    - ``representative_path`` — ``relative_path`` of a representative image
    - ``image_paths`` — comma-separated list of all images containing this face

    ChromaDB data is stored under ``<db_path>/faces/``.
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._collection: Any = None
        self._tmp_dir: Path | None = None
        self._created_at: datetime | None = None
        self._meta_cache: dict[str, dict[str, str]] | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_collection(self) -> Any:
        if self._collection is None:
            raise RuntimeError(
                "ChromaFaceIndexStore not initialised. Call load() or create_empty() first."
            )
        return self._collection

    def _get_embedding_dim(self) -> int | None:
        """Return embedding dimension from the first stored vector, or None if empty."""
        col = self._require_collection()
        if col.count() == 0:
            return None
        sample = col.get(limit=1, include=["embeddings"])
        embs = sample.get("embeddings") or []
        return len(embs[0]) if embs else None

    # ------------------------------------------------------------------
    # IndexStore — read
    # ------------------------------------------------------------------

    def search(self, query: FaceItem, top_k: int) -> list[IndexResult[FaceItem]]:
        """Return the *top_k* face clusters nearest to *query.embedding*."""
        col = self._require_collection()
        effective_n = min(top_k, col.count())
        if effective_n == 0:
            return []
        results = col.query(
            query_embeddings=[query.embedding],
            n_results=effective_n,
            include=["metadatas", "distances", "embeddings"],
        )
        out: list[IndexResult[FaceItem]] = []
        ids = results.get("ids", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        embeddings = results.get("embeddings", [[]])[0]
        for id_, meta, dist, emb in zip(ids, metadatas, distances, embeddings, strict=True):
            score = max(0.0, 1.0 - dist)
            out.append(
                IndexResult(
                    id=id_,
                    relative_path=meta.get("representative_path", id_),
                    item=FaceItem(embedding=list(emb), cluster_id=id_),
                    score=score,
                    extra={
                        "count": meta.get("count", "0"),
                        "image_paths": meta.get("image_paths", ""),
                    },
                )
            )
        return out

    def get_metadata(self, id: str) -> dict[str, str] | None:
        col = self._require_collection()
        if self._meta_cache is None:
            result = col.get(include=["metadatas"])
            self._meta_cache = {
                doc_id: meta
                for doc_id, meta in zip(result["ids"], result["metadatas"], strict=True)
            }
        return self._meta_cache.get(id)

    def list_all(self, top_k: int) -> list[IndexResult[FaceItem]]:
        """Return clusters sorted by frequency (descending count)."""
        col = self._require_collection()
        total = col.count()
        if total == 0:
            return []
        results = col.get(include=["metadatas", "embeddings"])
        ids: list[str] = results.get("ids", [])
        metadatas: list[dict[str, str]] = results.get("metadatas", [])
        embeddings: list[list[float]] = results.get("embeddings", [])

        rows: list[tuple[int, str, dict[str, str], list[float]]] = []
        for id_, meta, emb in zip(ids, metadatas, embeddings, strict=True):
            count = int(meta.get("count", "0"))
            rows.append((count, id_, meta, list(emb)))

        rows.sort(key=lambda r: r[0], reverse=True)
        max_count = rows[0][0] if rows else 1

        out: list[IndexResult[FaceItem]] = []
        for count, id_, meta, emb in rows[:top_k]:
            out.append(
                IndexResult(
                    id=id_,
                    relative_path=meta.get("representative_path", id_),
                    item=FaceItem(embedding=emb, cluster_id=id_),
                    score=count / max(max_count, 1),
                    extra={
                        "count": str(count),
                        "image_paths": meta.get("image_paths", ""),
                    },
                )
            )
        return out

    # ------------------------------------------------------------------
    # IndexStore — write
    # ------------------------------------------------------------------

    def add(self, id: str, item: FaceItem, metadata: dict[str, str]) -> None:
        col = self._require_collection()
        col.add(ids=[id], embeddings=[item.embedding], metadatas=[metadata])
        if self._meta_cache is not None:
            self._meta_cache[id] = metadata

    def upsert(self, id: str, item: FaceItem, metadata: dict[str, str]) -> None:
        col = self._require_collection()
        col.upsert(ids=[id], embeddings=[item.embedding], metadatas=[metadata])
        if self._meta_cache is not None:
            self._meta_cache[id] = metadata

    def upsert_batch(
        self,
        ids: list[str],
        items: list[FaceItem],
        metadatas: list[dict[str, str]],
    ) -> None:
        if not ids:
            return
        col = self._require_collection()
        embeddings = [item.embedding for item in items]
        col.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas)
        if self._meta_cache is not None:
            for id_, meta in zip(ids, metadatas, strict=True):
                self._meta_cache[id_] = meta

    # ------------------------------------------------------------------
    # IndexStore — lifecycle
    # ------------------------------------------------------------------

    def load(self, local_path: Path) -> None:
        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.PersistentClient(
            path=str(local_path / _SUB_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_collection(_COLLECTION_NAME)

    def create_empty(self) -> None:
        import chromadb
        from chromadb.config import Settings

        tmp_dir = Path(tempfile.mkdtemp(prefix="chroma_face_"))
        try:
            client = chromadb.PersistentClient(
                path=str(tmp_dir / _SUB_DIR),
                settings=Settings(anonymized_telemetry=False),
            )
            collection = client.create_collection(_COLLECTION_NAME)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        self._tmp_dir = tmp_dir
        self._client = client
        self._collection = collection
        self._created_at = None
        self._meta_cache = None

    def save(self, local_path: Path) -> None:
        if self._tmp_dir is None:
            raise RuntimeError(
                "save() requires the store to have been initialised via create_empty() "
                "or load_for_update(). load() is for read queries only."
            )
        self._client = None
        self._collection = None
        self._meta_cache = None
        tmp_dir = self._tmp_dir
        self._tmp_dir = None
        created_ts = (self._created_at or datetime.now(UTC)).isoformat()
        self._created_at = None
        try:
            dest = local_path / _SUB_DIR
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_dir / _SUB_DIR), str(dest))
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        finally:
            _ = created_ts  # used above; suppress unused warning

    def created_at(self, local_path: Path) -> datetime | None:
        # Delegate to the shared db_meta.json written by ChromaCaptionIndexStore.
        meta_path = local_path / "db_meta.json"
        if not meta_path.exists():
            return None
        try:
            data = json.loads(meta_path.read_text())
            return datetime.fromisoformat(data["created_at"])
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def load_for_update(self, local_path: Path) -> None:
        import chromadb
        from chromadb.config import Settings

        src = local_path / _SUB_DIR
        if not src.exists():
            raise FileNotFoundError(f"Face store directory not found: {src}")
        tmp_dir = Path(tempfile.mkdtemp(prefix="chroma_face_upd_"))
        try:
            shutil.copytree(str(src), str(tmp_dir / _SUB_DIR))
            client = chromadb.PersistentClient(
                path=str(tmp_dir / _SUB_DIR),
                settings=Settings(anonymized_telemetry=False),
            )
            collection = client.get_collection(_COLLECTION_NAME)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        self._tmp_dir = tmp_dir
        self._client = client
        self._collection = collection
        self._created_at = self.created_at(local_path)
        self._meta_cache = None

    def checkpoint(self, local_path: Path) -> None:
        if self._tmp_dir is None:
            raise RuntimeError(
                "checkpoint() requires the store to be initialised via "
                "create_empty() or load_for_update()"
            )
        dest = local_path / _SUB_DIR
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(self._tmp_dir / _SUB_DIR), str(dest))
