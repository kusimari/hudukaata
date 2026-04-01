"""BLIP-2 caption model (default implementation)."""

from __future__ import annotations

import json as _json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from common.media import MediaFile

from indexer.models.base import CaptionModel

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
        load_in_8bit: bool = False,
    ) -> None:
        self.image_checkpoint = image_checkpoint
        self.whisper_model = whisper_model
        self.max_new_tokens = max_new_tokens
        self._device = device
        self._load_in_8bit = load_in_8bit
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
            if self._load_in_8bit:
                # 8-bit quantisation halves VRAM with negligible quality impact.
                # Requires bitsandbytes: pip install bitsandbytes
                mdl = Blip2ForConditionalGeneration.from_pretrained(
                    self.image_checkpoint,
                    load_in_8bit=True,
                    device_map="auto",
                )
            else:
                mdl = Blip2ForConditionalGeneration.from_pretrained(
                    self.image_checkpoint,
                    torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                ).to(torch.device(device))  # type: ignore[arg-type]  # transformers _Wrapped typing bug
            self._processor, self._model = proc, mdl

    def _load_whisper(self) -> None:
        if self._whisper is None:
            import whisper

            download_root = os.environ.get("WHISPER_MODEL_DIR") or None
            self._whisper = whisper.load_model(self.whisper_model, download_root=download_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def caption_batch(
        self,
        mfs: list[MediaFile],
        pil_images: list[object] | None = None,
    ) -> list[str]:
        """Caption a batch, using a single BLIP-2 forward pass for images.

        Video and audio files are processed individually (they require
        per-file frame extraction / Whisper transcription).

        Args:
            mfs: Media files to caption.
            pil_images: Optional pre-loaded PIL ``Image`` objects supplied by
                :class:`~indexer.pipeline.PrefetchSource`.  When an entry is
                not ``None``, it is used directly instead of opening the file
                from disk, avoiding redundant IO during GPU inference.
        """
        if not mfs:
            return []

        results: list[str] = [""] * len(mfs)
        image_indices = [i for i, mf in enumerate(mfs) if mf.media_type == "image"]
        other_indices = [i for i, mf in enumerate(mfs) if mf.media_type != "image"]

        # True GPU batch for images
        if image_indices:
            try:
                import torch
                from PIL import Image

                self._load_blip2()
                device = self._get_device()
                # Use pre-loaded PIL images when available; fall back to disk otherwise.
                loaded: list[object] = []
                for i in image_indices:
                    pre = pil_images[i] if pil_images is not None else None
                    loaded.append(
                        pre if pre is not None else Image.open(mfs[i].local_path).convert("RGB")
                    )
                torch_dtype = torch.float16 if device == "cuda" else torch.float32
                inputs = self._processor(images=loaded, return_tensors="pt", padding=True).to(
                    device, torch_dtype
                )
                generated_ids = self._model.generate(**inputs, max_new_tokens=self.max_new_tokens)
                captions = self._processor.batch_decode(generated_ids, skip_special_tokens=True)
                for idx, cap in zip(image_indices, captions, strict=False):
                    results[idx] = cap.strip()
            except Exception as exc:
                logger.warning("Batch image captioning failed (%s); falling back per-image", exc)
                for i in image_indices:
                    try:
                        results[i] = self._caption_image(mfs[i].local_path)
                    except Exception as inner:
                        logger.warning("Skipping image %s: %s", mfs[i].relative_path, inner)

        # Video and audio always single-file
        for i in other_indices:
            try:
                results[i] = self.caption(mfs[i])
            except Exception as exc:
                logger.warning("Skipping %s: %s", mfs[i].relative_path, exc)

        return results

    def caption(self, mf: MediaFile) -> str:
        if mf.media_type == "image":
            return self._caption_image(mf.local_path)
        if mf.media_type == "video":
            frame_paths: list[Path] = []
            try:
                frame_paths = self._extract_frames(mf.local_path)
                captions = [self._caption_image(p) for p in frame_paths]
                return " | ".join(c for c in captions if c)
            finally:
                for p in frame_paths:
                    p.unlink(missing_ok=True)
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

    def _extract_frames(self, path: Path) -> list[Path]:
        """Extract frames at 0%, 25%, 50%, 75% of video duration."""
        try:
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
            logger.warning("ffprobe failed for %s: %s; extracting from start only", path, exc)
            duration = 0.0

        offsets = [0.0, duration * 0.25, duration * 0.5, duration * 0.75]
        frame_paths: list[Path] = []
        for i, offset in enumerate(offsets):
            fd, tmp_str = tempfile.mkstemp(suffix=".jpg", prefix=f"indexer_frame{i}_")
            os.close(fd)
            tmp = Path(tmp_str)
            try:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-ss",
                        str(offset),
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
                frame_paths.extend(Blip2CaptionModel._filter_frame_files([tmp]))
            except Exception as exc:
                tmp.unlink(missing_ok=True)
                logger.warning(
                    "Failed to extract frame at offset %.2f from %s: %s", offset, path, exc
                )
        return frame_paths

    @staticmethod
    def _filter_frame_files(candidates: list[Path]) -> list[Path]:
        """Return only non-empty files from *candidates*; delete the empty ones."""
        valid: list[Path] = []
        for p in candidates:
            if p.exists() and p.stat().st_size > 0:
                valid.append(p)
            else:
                p.unlink(missing_ok=True)
                logger.debug("ffmpeg wrote empty frame %s; skipping", p)
        return valid

    def _transcribe_audio(self, path: Path) -> str:
        self._load_whisper()
        result: dict[str, Any] = self._whisper.transcribe(str(path))
        text: str = result.get("text", "").strip()
        return text
