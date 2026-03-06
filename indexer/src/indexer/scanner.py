"""Scanner — recursive media-file discovery via a MediaPointer."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from indexer.pointer import MediaPointer

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".tiff",
    ".heic",
    ".heif",
    ".avif",
}
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
}
AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".aac",
    ".ogg",
    ".m4a",
    ".opus",
    ".wma",
}

_EXT_TO_TYPE: dict[str, Literal["image", "video", "audio"]] = {
    **{ext: "image" for ext in IMAGE_EXTENSIONS},
    **{ext: "video" for ext in VIDEO_EXTENSIONS},
    **{ext: "audio" for ext in AUDIO_EXTENSIONS},
}


@dataclass
class MediaFile:
    relative_path: str
    local_path: Path
    media_type: Literal["image", "video", "audio"]


def scan(pointer: MediaPointer) -> Iterator[MediaFile]:
    """Yield a MediaFile for every recognised media file under *pointer*."""
    for relative_path, local_path in pointer.iter_files():
        ext = Path(relative_path).suffix.lower()
        media_type = _EXT_TO_TYPE.get(ext)
        if media_type is None:
            continue
        yield MediaFile(
            relative_path=relative_path,
            local_path=local_path,
            media_type=media_type,
        )
