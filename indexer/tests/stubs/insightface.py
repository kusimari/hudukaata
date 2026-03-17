"""Stub InsightFaceModel — returns deterministic face embeddings without loading real models."""

from __future__ import annotations

from common.media import MediaFile

from indexer.models.insightface import InsightFaceModel

_EMBEDDING_DIM = 512


class StubInsightFaceModel(InsightFaceModel):
    """Returns *n* deterministic face embeddings per image without loading InsightFace.

    Args:
        faces_per_image: Number of face embeddings to return for each image file.
            Non-image media always returns zero faces.
    """

    def __init__(self, faces_per_image: int = 1) -> None:
        super().__init__()  # sets self._app = None; never loaded
        self._faces_per_image = faces_per_image

    def detect_batch(self, mfs: list[MediaFile]) -> list[list[list[float]]]:
        result = []
        for i, mf in enumerate(mfs):
            if mf.media_type != "image":
                result.append([])
            else:
                # Each face gets a distinct deterministic embedding vector.
                faces = [
                    [float((i * self._faces_per_image + j + 1) % 256) / 256.0] * _EMBEDDING_DIM
                    for j in range(self._faces_per_image)
                ]
                result.append(faces)
        return result
