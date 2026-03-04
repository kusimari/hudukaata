"""EXIF / media metadata extraction."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from indexer.scanner import MediaFile


def extract_exif(mf: MediaFile) -> dict[str, str]:
    """Return a flat dict of metadata key→value strings for *mf*.

    Unknown / unreadable tags are silently skipped.
    """
    if mf.media_type == "image":
        return _extract_image(mf.local_path)
    if mf.media_type == "video":
        return _extract_video(mf.local_path)
    if mf.media_type == "audio":
        return _extract_audio(mf.local_path)
    return {}


# ---------------------------------------------------------------------------
# Image — Pillow + exifread
# ---------------------------------------------------------------------------

def _extract_image(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}

    # exifread for rich EXIF tags
    try:
        import exifread
        with open(path, "rb") as fh:
            tags = exifread.process_file(fh, details=False)
        for key, val in tags.items():
            clean_key = key.replace(" ", "_").replace("/", "_")
            result[clean_key] = str(val)
    except Exception:
        pass

    # Pillow for basic image attributes and GPS
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        img = Image.open(path)
        result["width"] = str(img.width)
        result["height"] = str(img.height)
        result["format"] = img.format or ""

        raw_exif = img._getexif()  # type: ignore[attr-defined]
        if raw_exif:
            for tag_id, value in raw_exif.items():
                tag_name = TAGS.get(tag_id, str(tag_id))
                if isinstance(value, bytes):
                    continue
                result.setdefault(str(tag_name), str(value))
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Video — ffprobe
# ---------------------------------------------------------------------------

def _extract_video(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout)

        fmt = data.get("format", {})
        for key in ("duration", "bit_rate", "size"):
            if key in fmt:
                result[key] = str(fmt[key])
        tags = fmt.get("tags", {})
        for key in ("creation_time", "title", "comment"):
            if key in tags:
                result[key] = str(tags[key])

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                for key in ("codec_name", "width", "height", "r_frame_rate"):
                    if key in stream:
                        result[key] = str(stream[key])
                break

    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Audio — mutagen
# ---------------------------------------------------------------------------

def _extract_audio(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(path)
        if audio is None:
            return result

        if hasattr(audio, "info"):
            info = audio.info
            if hasattr(info, "length"):
                result["duration"] = str(info.length)
            if hasattr(info, "bitrate"):
                result["bitrate"] = str(info.bitrate)

        for key, val in (audio.tags or {}).items():
            clean_key = str(key).lower().replace("/", "_")
            result[clean_key] = str(val[0] if isinstance(val, list) else val)

    except Exception:
        pass

    return result
