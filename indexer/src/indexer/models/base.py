"""CaptionModel abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from common.media import MediaFile


class CaptionModel(ABC):
    @abstractmethod
    def caption(self, mf: MediaFile) -> str:
        """Return a human-readable text description of the media file."""
        ...

    def supports(self, media_type: str) -> bool:
        """Return True if this model handles the given media_type."""
        return True
