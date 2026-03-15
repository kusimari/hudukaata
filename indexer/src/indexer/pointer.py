"""Thin re-export shim — all media source types are now in common.media.

Backward-compat aliases are provided so existing code that imports
``FileMediaPointer``, ``RcloneMediaPointer``, or ``GoogleColabMediaPointer``
from this module continues to work without changes.

``MediaPointer.parse()`` delegates to :meth:`common.media.MediaSource.from_uri`.
Direct construction ``MediaPointer(scheme=..., remote=..., path=...)`` is
preserved for existing callers and test code.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal, cast

from common.base import StorePointer as StorePointer  # noqa: F401
from common.media import (
    FileMediaSource as FileMediaSource,
)
from common.media import (
    GdriveMediaSource as GdriveMediaSource,
)
from common.media import (
    MediaFile as MediaFile,
)
from common.media import (
    MediaSource as MediaSource,
)
from common.media import (
    RcloneMediaSource as RcloneMediaSource,
)
from common.media import (
    _LocalFile as _LocalFile,
)
from common.media import (
    _rclone_lsjson as _rclone_lsjson,
)

# ---------------------------------------------------------------------------
# Backward-compat aliases
# ---------------------------------------------------------------------------

FileMediaPointer = FileMediaSource
RcloneMediaPointer = RcloneMediaSource
GoogleColabMediaPointer = GdriveMediaSource


# ---------------------------------------------------------------------------
# MediaPointer — backward-compatible factory shim
# ---------------------------------------------------------------------------


class MediaPointer(MediaSource):
    """Backward-compatible URI-parsing factory and direct-construction shim.

    ``parse()`` returns the appropriate :class:`~common.media.MediaSource`
    subclass.  For new code, prefer :meth:`~common.media.MediaSource.from_uri`
    or constructing :class:`~common.media.FileMediaSource` /
    :class:`~common.media.RcloneMediaSource` directly.

    This class also remains constructible as
    ``MediaPointer(scheme=..., remote=..., path=...)`` so existing code that
    builds pointers without parsing a URI string continues to work.
    Its ``scan()`` and ``getmedia()`` delegate to the concrete implementation.
    """

    def __init__(
        self,
        scheme: Literal["file", "rclone"],
        remote: str | None,
        path: str,
    ) -> None:
        self.scheme = scheme
        self.remote = remote
        self.path = path

    @property
    def uri(self) -> str:
        if self.scheme == "file":
            return f"file://{self.path}"
        return f"rclone:{self.remote}:///{self.path}"

    @classmethod
    def parse(cls, uri: str) -> MediaSource:
        """Parse a URI and return the appropriate :class:`~common.media.MediaSource`."""
        return MediaSource.from_uri(uri)

    def scan(self, subfolder: str | None = None) -> Iterator[MediaFile]:
        if self.scheme == "file":
            yield from FileMediaSource(path=self.path).scan(subfolder=subfolder)
        else:
            yield from RcloneMediaSource(
                remote=cast(str, self.remote),
                path=self.path,
            ).scan(subfolder=subfolder)

    def getmedia(self, relative_path: str) -> MediaFile:
        if self.scheme == "file":
            return FileMediaSource(path=self.path).getmedia(relative_path)
        return RcloneMediaSource(
            remote=cast(str, self.remote),
            path=self.path,
        ).getmedia(relative_path)
