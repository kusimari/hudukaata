"""Text formatting utilities for building vectorizer input strings."""

from __future__ import annotations


def format_text(caption: str, exif: dict[str, str]) -> str:
    """Build the combined text fed to the vectorizer."""
    lines = [caption]
    if exif:
        lines += ["", "EXIF:"]
        lines.extend(f"{k}: {v}" for k, v in sorted(exif.items()))
    return "\n".join(lines)
