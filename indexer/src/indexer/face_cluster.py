"""FaceClusterer — incremental centroid-based face clustering.

Each detected face vector is compared to existing cluster centroids using
cosine similarity.  If the best match exceeds *threshold*, the face is
assigned to that cluster and the centroid is updated via a running average.
Otherwise a new cluster is created.

The cluster state is persisted in an :class:`~common.index.IndexStore` (the
face store).  Existing clusters are loaded lazily on the first
:meth:`FaceClusterer.assign` call, which happens after the pipeline runner
has initialised the face store.
"""

from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING

from common.index import FaceItem

if TYPE_CHECKING:
    from indexer.stores.chroma_face import ChromaFaceIndexStore


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [−1, 1] between vectors *a* and *b*."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class FaceClusterer:
    """Incrementally cluster face vectors against stored centroids.

    Args:
        face_store: Backing store that persists cluster centroids and metadata.
        threshold: Cosine similarity above which a face is merged into an
            existing cluster.  Typical range: 0.5–0.8.
    """

    def __init__(
        self,
        face_store: ChromaFaceIndexStore,
        threshold: float = 0.6,
    ) -> None:
        self._store = face_store
        self._threshold = threshold
        # None = not yet loaded from store; loaded lazily on first assign().
        # Mapping: cluster_id → (centroid, count, image_paths)
        self._clusters: dict[str, tuple[list[float], int, list[str]]] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assign(self, face_vector: list[float], image_path: str) -> str:
        """Assign *face_vector* to the nearest cluster, creating one if needed.

        Side-effects: updates the cluster centroid and metadata in the face
        store so that incremental indexing picks up existing clusters.

        Args:
            face_vector: Embedding vector for one detected face.
            image_path: ``relative_path`` of the image containing this face.

        Returns:
            The cluster ID assigned to this face.
        """
        if self._clusters is None:
            self._load_existing()

        best_id, best_sim = self._find_nearest(face_vector)

        if best_id is not None and best_sim >= self._threshold:
            return self._update_cluster(best_id, face_vector, image_path)
        return self._create_cluster(face_vector, image_path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_existing(self) -> None:
        """Load existing cluster centroids from the face store into memory."""
        self._clusters = {}
        for r in self._store.list_all(top_k=100_000):
            image_paths_str = r.extra.get("image_paths", "")
            image_paths = [p for p in image_paths_str.split(",") if p]
            count = int(r.extra.get("count", "1"))
            self._clusters[r.item.cluster_id] = (r.item.embedding, count, image_paths)

    def _find_nearest(self, face_vector: list[float]) -> tuple[str | None, float]:
        assert self._clusters is not None
        best_id: str | None = None
        best_sim = -2.0
        for cluster_id, (centroid, _, _) in self._clusters.items():
            sim = _cosine_sim(face_vector, centroid)
            if sim > best_sim:
                best_sim = sim
                best_id = cluster_id
        return best_id, best_sim

    def _update_cluster(
        self,
        cluster_id: str,
        face_vector: list[float],
        image_path: str,
    ) -> str:
        assert self._clusters is not None
        centroid, count, image_paths = self._clusters[cluster_id]
        new_count = count + 1
        # Running average update for centroid.
        new_centroid = [
            (centroid[i] * count + face_vector[i]) / new_count for i in range(len(centroid))
        ]
        new_paths = image_paths if image_path in image_paths else [*image_paths, image_path]
        self._clusters[cluster_id] = (new_centroid, new_count, new_paths)
        self._persist(cluster_id, new_centroid, new_count, new_paths[0], new_paths)
        return cluster_id

    def _create_cluster(self, face_vector: list[float], image_path: str) -> str:
        assert self._clusters is not None
        cluster_id = str(uuid.uuid4())
        self._clusters[cluster_id] = (face_vector, 1, [image_path])
        self._persist(cluster_id, face_vector, 1, image_path, [image_path])
        return cluster_id

    def _persist(
        self,
        cluster_id: str,
        centroid: list[float],
        count: int,
        representative_path: str,
        image_paths: list[str],
    ) -> None:
        metadata: dict[str, str] = {
            "count": str(count),
            "representative_path": representative_path,
            "image_paths": ",".join(image_paths),
        }
        self._store.upsert(
            cluster_id,
            FaceItem(embedding=centroid, cluster_id=cluster_id),
            metadata,
        )
