"""CaptionModel abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from common.media import MediaFile


class CaptionModel(ABC):
    @abstractmethod
    def caption(self, mf: MediaFile) -> str:
        """Return a human-readable text description of the media file."""
        ...

    def caption_batch(
        self,
        mfs: list[MediaFile],
        pil_images: list[object] | None = None,
    ) -> list[str]:
        """Caption a batch of media files.

        Default implementation calls :meth:`caption` once per file.
        Subclasses may override for true batch inference (e.g. GPU batching).

        Args:
            mfs: Media files to caption.
            pil_images: Optional pre-loaded PIL ``Image`` objects (one per
                entry in *mfs*, ``None`` for an entry to fall back to disk).
                Subclasses should use these to avoid redundant IO.
        """
        return [self.caption(mf) for mf in mfs]

    def supports(self, media_type: str) -> bool:
        """Return True if this model handles the given media_type."""
        return True
