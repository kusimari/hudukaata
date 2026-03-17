"""ChromaCaptionIndexStore — Chroma + SentenceTransformer implementation of IndexStore[CaptionItem].

All vectorization is internal.  Callers pass and receive :class:`~common.index.CaptionItem`
objects.  The ChromaDB data lives under ``<db_path>/captions/``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.index import CaptionItem, IndexResult, IndexStore

from indexer.vectorizers.base import Vectorizer

_META_FILE = "db_meta.json"
_COLLECTION_NAME = "media"
_SUB_DIR = "captions"


class ChromaCaptionIndexStore(IndexStore[CaptionItem]):
    """Caption-based semantic search: SentenceTransformer vectors + ChromaDB storage.

    ChromaDB data is stored under ``<db_path>/captions/`` so that caption and
    face stores can share the same ``db_path`` root.

    Inject *vectorizer* for testing; leave ``None`` to use the default
    :class:`~indexer.vectorizers.sentence_transformer.SentenceTransformerVectorizer`.
    """

    def __init__(self, vectorizer: Vectorizer | None = None) -> None:
        if vectorizer is not None:
            self._vec: Vectorizer = vectorizer
        else:
            from indexer.vectorizers.sentence_transformer import SentenceTransformerVectorizer

            self._vec = SentenceTransformerVectorizer()
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
                "ChromaCaptionIndexStore not initialised. Call load() or create_empty() first."
            )
        return self._collection

    # ------------------------------------------------------------------
    # IndexStore — read
    # ------------------------------------------------------------------

    def search(self, query: CaptionItem, top_k: int) -> list[IndexResult[CaptionItem]]:
        col = self._require_collection()
        vector = self._vec.vectorize(query.text)
        effective_n = min(top_k, col.count())
        if effective_n == 0:
            return []
        results = col.query(
            query_embeddings=[vector],
            n_results=effective_n,
            include=["metadatas", "distances"],
        )
        out: list[IndexResult[CaptionItem]] = []
        ids = results.get("ids", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for id_, meta, dist in zip(ids, metadatas, distances, strict=True):
            score = max(0.0, 1.0 - dist)
            out.append(
                IndexResult(
                    id=id_,
                    relative_path=meta.get("relative_path", id_),
                    item=CaptionItem(text=meta.get("caption", "")),
                    score=score,
                    extra={k: v for k, v in meta.items() if k not in ("relative_path", "caption")},
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

    # ------------------------------------------------------------------
    # IndexStore — write
    # ------------------------------------------------------------------

    def add(self, id: str, item: CaptionItem, metadata: dict[str, str]) -> None:
        col = self._require_collection()
        vector = self._vec.vectorize(item.text)
        col.add(ids=[id], embeddings=[vector], metadatas=[metadata])

    def upsert(self, id: str, item: CaptionItem, metadata: dict[str, str]) -> None:
        col = self._require_collection()
        vector = self._vec.vectorize(item.text)
        col.upsert(ids=[id], embeddings=[vector], metadatas=[metadata])
        if self._meta_cache is not None:
            self._meta_cache[id] = metadata

    def upsert_batch(
        self,
        ids: list[str],
        items: list[CaptionItem],
        metadatas: list[dict[str, str]],
    ) -> None:
        """Vectorise all captions in one encoder pass and write to ChromaDB in one call."""
        if not ids:
            return
        col = self._require_collection()
        texts = [item.text for item in items]
        vectors = self._vec.vectorize_batch(texts)
        col.upsert(ids=ids, embeddings=vectors, metadatas=metadatas)
        if self._meta_cache is not None:
            for id_, meta in zip(ids, metadatas, strict=True):
                self._meta_cache[id_] = meta

    # ------------------------------------------------------------------
    # IndexStore — lifecycle
    # ------------------------------------------------------------------

    def load(self, local_path: Path) -> None:
        import chromadb
        from chromadb.config import Settings

        # Detect old layout (pre-3.0.0): ChromaDB data was stored directly in
        # local_path instead of local_path/captions/.  A chroma.sqlite3 file at
        # the root is the tell-tale sign.
        if (local_path / "chroma.sqlite3").exists() and not (local_path / _SUB_DIR).exists():
            raise RuntimeError(
                f"Index at {local_path} uses the old pre-3.0.0 layout "
                f"(ChromaDB data at root instead of {local_path / _SUB_DIR}). "
                "Re-run the indexer to rebuild the index with the current layout."
            )

        self._client = chromadb.PersistentClient(
            path=str(local_path / _SUB_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_collection(_COLLECTION_NAME)

    def create_empty(self) -> None:
        import chromadb
        from chromadb.config import Settings

        tmp_dir = Path(tempfile.mkdtemp(prefix="chroma_cap_"))
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
            (tmp_dir / _META_FILE).write_text(json.dumps({"created_at": created_ts}))
            dest = local_path / _SUB_DIR
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_dir / _SUB_DIR), str(dest))
            (local_path / _META_FILE).write_text(json.dumps({"created_at": created_ts}))
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def created_at(self, local_path: Path) -> datetime | None:
        meta_path = local_path / _META_FILE
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
        tmp_dir = Path(tempfile.mkdtemp(prefix="chroma_cap_upd_"))
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
