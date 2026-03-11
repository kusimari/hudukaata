"""Shared pytest fixtures — includes real sample media files."""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def sample_image_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small but valid JPEG (32x32 coloured square) generated with Pillow."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    path = tmp_path_factory.mktemp("media") / "sample.jpg"
    Image.new("RGB", (32, 32), color=(200, 100, 50)).save(path, "JPEG")
    return path


@pytest.fixture(scope="session")
def sample_audio_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small but valid WAV (1 second, mono, 8 kHz silence)."""
    path = tmp_path_factory.mktemp("media") / "sample.wav"
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00\x00" * 8000)
    return path


@pytest.fixture(scope="session")
def sample_video_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small MP4 (2 second, 64x64 blue, 1 fps) generated with ffmpeg.

    ffmpeg is guaranteed by the Nix devShell; if it is absent the test will
    fail loudly so the environment setup can be fixed.
    """
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:size=64x64:duration=2:rate=1",
                str(path),
            ],
            capture_output=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        pytest.fail(f"ffmpeg not available or failed: {exc}\nFix: run `nix develop .#indexer`")
    return path
