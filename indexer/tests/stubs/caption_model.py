"""Stub caption model — returns the filename as caption."""

from __future__ import annotations

from common.media import MediaFile

from indexer.models.base import CaptionModel


class StubCaptionModel(CaptionModel):
    def caption(self, mf: MediaFile) -> str:
        return mf.relative_path

    def caption_batch(
        self,
        mfs: list[MediaFile],
        pil_images: list[object] | None = None,
    ) -> list[str]:
        return [self.caption(mf) for mf in mfs]
