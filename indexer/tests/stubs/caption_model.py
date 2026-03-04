"""Stub caption model — returns the filename as caption."""

from __future__ import annotations

from indexer.models.base import CaptionModel
from indexer.scanner import MediaFile


class StubCaptionModel(CaptionModel):
    def caption(self, mf: MediaFile) -> str:
        return mf.relative_path
