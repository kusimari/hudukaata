"""Stub caption model — returns the filename as caption."""

from __future__ import annotations

from common.media import MediaFile

from indexer.models.base import CaptionModel


class StubCaptionModel(CaptionModel):
    def caption(self, mf: MediaFile) -> str:
        return mf.relative_path
