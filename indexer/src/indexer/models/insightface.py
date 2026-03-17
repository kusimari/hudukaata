"""InsightFaceModel — face detection and embedding using InsightFace (ArcFace/RetinaFace)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from common.media import MediaFile

logger = logging.getLogger(__name__)

# Number of face embedding dimensions (ArcFace default).
_EMBEDDING_DIM = 512


class InsightFaceModel:
    """Detect faces and return ArcFace embeddings using InsightFace.

    Lazy-loads the InsightFace model on first use.  Requires
    ``insightface`` and ``opencv-python`` to be installed.

    Args:
        ctx_id: Device context ID.  ``-1`` = CPU; ``0``, ``1``, … = GPU index.
    """

    def __init__(self, ctx_id: int = -1) -> None:
        self._ctx_id = ctx_id
        self._app: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_batch(self, mfs: list[MediaFile]) -> list[list[list[float]]]:
        """Detect faces in a batch of media files.

        Args:
            mfs: Media files to process.

        Returns:
            One entry per media file.  Each entry is a list of face embeddings
            (each embedding is a list of floats).  Non-image media returns ``[]``.
        """
        result: list[list[list[float]]] = []
        for mf in mfs:
            if mf.media_type != "image":
                result.append([])
                continue
            try:
                result.append(self._detect_one(mf.local_path))
            except Exception as exc:
                logger.warning("Face detection failed for %s: %s", mf.relative_path, exc)
                result.append([])
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_app(self) -> None:
        if self._app is not None:
            return
        import insightface  # type: ignore[import-not-found]

        app = insightface.app.FaceAnalysis(
            allowed_modules=["detection", "recognition"],
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=self._ctx_id)
        self._app = app

    def _detect_one(self, path: Path) -> list[list[float]]:
        import cv2  # type: ignore[import-not-found]

        self._load_app()
        img = cv2.imread(str(path))
        if img is None:
            return []
        faces = self._app.get(img)
        return [face.embedding.tolist() for face in faces if face.embedding is not None]
