"""BLIP-2 caption model (default implementation)."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from indexer.models.base import CaptionModel
from indexer.scanner import MediaFile

logger = logging.getLogger(__name__)

# Maximum caption length in tokens; tune via constructor parameter.
_DEFAULT_MAX_NEW_TOKENS = 50


class Blip2CaptionModel(CaptionModel):
    def __init__(
        self,
        image_checkpoint: str = "Salesforce/blip2-opt-2.7b",
        whisper_model: str = "base",
        device: str | None = None,
        max_new_tokens: int = _DEFAULT_MAX_NEW_TOKENS,
    ) -> None:
        self.image_checkpoint = image_checkpoint
        self.whisper_model = whisper_model
        self.max_new_tokens = max_new_tokens
        self._device = device
        self._processor: Any = None
        self._model: Any = None
        self._whisper: Any = None

    # ------------------------------------------------------------------
    # Lazy loaders
    # ------------------------------------------------------------------

    def _get_device(self) -> str:
        if self._device:
            return self._device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _load_blip2(self) -> None:
        if self._processor is None:
            import torch
            from transformers import Blip2ForConditionalGeneration, Blip2Processor

            device = self._get_device()
            # Load both atomically so a mid-load failure leaves _processor as None.
            proc = Blip2Processor.from_pretrained(self.image_checkpoint)
            mdl = Blip2ForConditionalGeneration.from_pretrained(
                self.image_checkpoint,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            ).to(torch.device(device))
            self._processor, self._model = proc, mdl

    def _load_whisper(self) -> None:
        if self._whisper is None:
            import whisper

            self._whisper = whisper.load_model(self.whisper_model)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def caption(self, mf: MediaFile) -> str:
        if mf.media_type == "image":
            return self._caption_image(mf.local_path)
        if mf.media_type == "video":
            tmp = self._extract_middle_frame(mf.local_path)
            try:
                return self._caption_image(tmp)
            finally:
                tmp.unlink(missing_ok=True)
        if mf.media_type == "audio":
            return self._transcribe_audio(mf.local_path)
        return ""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _caption_image(self, path: Path) -> str:
        import torch
        from PIL import Image

        self._load_blip2()
        device = self._get_device()
        image = Image.open(path).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt").to(
            device,
            torch.float16 if device == "cuda" else torch.float32,
        )
        generated_ids = self._model.generate(**inputs, max_new_tokens=self.max_new_tokens)
        decoded: str = self._processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return decoded.strip()

    def _extract_middle_frame(self, path: Path) -> Path:
        """Extract the middle keyframe of a video to a temp JPEG and return its path."""
        fd, tmp_str = tempfile.mkstemp(suffix=".jpg", prefix="indexer_frame_")
        # Close the fd immediately; ffmpeg will write to the path.
        os.close(fd)
        tmp = Path(tmp_str)

        try:
            # Get duration via ffprobe
            try:
                import json as _json

                proc = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "quiet",
                        "-print_format",
                        "json",
                        "-show_format",
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                duration = float(_json.loads(proc.stdout)["format"].get("duration", 0))
            except Exception as exc:
                logger.warning("ffprobe failed for %s: %s; seeking to start of file", path, exc)
                duration = 0.0

            midpoint = duration / 2
            subprocess.run(
                [
                    "ffmpeg",
                    "-ss",
                    str(midpoint),
                    "-i",
                    str(path),
                    "-vframes",
                    "1",
                    "-q:v",
                    "2",
                    str(tmp),
                    "-y",
                ],
                capture_output=True,
                check=True,
            )
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        return tmp

    def _transcribe_audio(self, path: Path) -> str:
        self._load_whisper()
        result: dict[str, Any] = self._whisper.transcribe(str(path))
        text: str = result.get("text", "").strip()
        return text
