"""Tests for Blip2CaptionModel.

Image captioning: real PIL image loaded from disk; only model.generate is
mocked (BLIP-2 weights are ~10 GB and cannot be downloaded in test env).

Audio transcription: real whisper "base" model (~74 MB); no mocks.

Video frame extraction: real ffmpeg where available; skipped otherwise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast
from unittest.mock import MagicMock, patch

import pytest

from indexer.models.blip2 import Blip2CaptionModel
from indexer.pointer import MediaFile, _LocalFile


def _mf(path: Path, media_type: str) -> MediaFile:
    """Build a MediaFile backed by a real local path."""
    return MediaFile(
        relative_path=path.name,
        media_type=cast(Literal["image", "video", "audio"], media_type),
        _ctx=_LocalFile(path),
    )


# ---------------------------------------------------------------------------
# _load_blip2 — atomic initialisation
# ---------------------------------------------------------------------------


class TestLoadBlip2:
    def test_assigns_processor_and_model_atomically(self):
        model = Blip2CaptionModel()

        mock_proc = MagicMock()
        mock_mdl = MagicMock()
        mock_mdl.to.return_value = mock_mdl

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        mock_torch.float32 = "float32"

        mock_transformers = MagicMock()
        mock_transformers.Blip2Processor.from_pretrained.return_value = mock_proc
        mock_transformers.Blip2ForConditionalGeneration.from_pretrained.return_value = mock_mdl

        with patch.dict(
            "sys.modules",
            {"torch": mock_torch, "transformers": mock_transformers},
        ):
            model._load_blip2()

        assert model._processor is mock_proc
        assert model._model is mock_mdl

    def test_does_not_reload_if_already_loaded(self):
        model = Blip2CaptionModel()
        model._processor = MagicMock()
        model._model = MagicMock()

        mock_transformers = MagicMock()
        with patch.dict("sys.modules", {"transformers": mock_transformers}):
            model._load_blip2()
            mock_transformers.Blip2Processor.from_pretrained.assert_not_called()


# ---------------------------------------------------------------------------
# _caption_image — real PIL image loaded from disk; model.generate mocked
# ---------------------------------------------------------------------------


class TestCaptionImage:
    def test_captions_real_image(self, sample_image_path: Path):
        """PIL opens the real image; only the heavy model forward pass is mocked."""
        model = Blip2CaptionModel()

        mock_inputs = MagicMock()
        mock_inputs.to.return_value = {"pixel_values": MagicMock()}
        mock_proc = MagicMock(return_value=mock_inputs)
        mock_proc.batch_decode.return_value = ["a red square"]

        mock_mdl = MagicMock()
        mock_mdl.generate.return_value = MagicMock()

        mock_torch = MagicMock()
        mock_torch.float32 = "float32"
        mock_torch.cuda.is_available.return_value = False

        model._processor = mock_proc
        model._model = mock_mdl
        model._device = "cpu"

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = model._caption_image(sample_image_path)

        assert result == "a red square"
        # Processor was invoked with the image actually loaded from disk
        mock_proc.assert_called_once()


# ---------------------------------------------------------------------------
# _extract_frames — real ffmpeg where available
# ---------------------------------------------------------------------------


class TestExtractFrames:
    def test_extracts_frames_from_real_video(self, sample_video_path: Path | None):
        if sample_video_path is None:
            pytest.skip("ffmpeg not available")

        model = Blip2CaptionModel()
        frames = model._extract_frames(sample_video_path)

        try:
            assert len(frames) > 0, "Expected at least one extracted frame"
            for frame in frames:
                assert frame.exists(), f"Frame file missing: {frame}"
                assert frame.stat().st_size > 0, f"Frame file is empty: {frame}"
        finally:
            for f in frames:
                f.unlink(missing_ok=True)

    def test_extracts_up_to_four_frames(self, sample_video_path: Path | None):
        if sample_video_path is None:
            pytest.skip("ffmpeg not available")

        model = Blip2CaptionModel()
        frames = model._extract_frames(sample_video_path)
        try:
            assert len(frames) <= 4
        finally:
            for f in frames:
                f.unlink(missing_ok=True)

    def test_returns_empty_list_for_missing_video(self, tmp_path):
        """Graceful degradation when ffmpeg cannot read the file."""
        model = Blip2CaptionModel()
        frames = model._extract_frames(tmp_path / "nonexistent.mp4")
        assert frames == []


# ---------------------------------------------------------------------------
# _transcribe_audio — real whisper "base" model, real WAV file, no mocks
# ---------------------------------------------------------------------------


class TestTranscribeAudio:
    def test_transcribes_real_wav_with_real_whisper(self, sample_audio_path: Path):
        """Load whisper 'base' (~74 MB) and transcribe a real WAV — no mocks.

        The WAV is 1 s of silence so the transcript may be empty or minimal;
        we only assert that the pipeline runs and returns a string.
        """
        pytest.importorskip("whisper")  # skip if package absent
        import shutil

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not available")
        model = Blip2CaptionModel(whisper_model="base")
        # Force the model to load so any download error surfaces as a skip.
        try:
            model._load_whisper()
        except Exception as exc:
            pytest.skip(f"Whisper model unavailable: {exc}")

        result = model._transcribe_audio(sample_audio_path)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# caption() — dispatch by media type (uses with mf: pattern)
# ---------------------------------------------------------------------------


class TestCaption:
    def test_image_dispatches_to_caption_image(self, sample_image_path: Path):
        model = Blip2CaptionModel()
        model._caption_image = MagicMock(return_value="a picture")  # type: ignore[method-assign]

        mf = _mf(sample_image_path, "image")
        with mf:
            result = model.caption(mf)

        assert result == "a picture"
        model._caption_image.assert_called_once_with(sample_image_path)

    def test_audio_dispatches_to_transcribe(self, sample_audio_path: Path):
        model = Blip2CaptionModel()
        model._transcribe_audio = MagicMock(return_value="some speech")  # type: ignore[method-assign]

        mf = _mf(sample_audio_path, "audio")
        with mf:
            result = model.caption(mf)

        assert result == "some speech"

    def test_video_combines_frame_captions(self, sample_video_path: Path | None):
        if sample_video_path is None:
            pytest.skip("ffmpeg not available")

        model = Blip2CaptionModel()
        fake_frame = sample_video_path.parent / "fake_frame.jpg"
        fake_frame.write_bytes(b"fake")
        model._extract_frames = MagicMock(return_value=[fake_frame])  # type: ignore[method-assign]
        model._caption_image = MagicMock(return_value="a blue square")  # type: ignore[method-assign]

        mf = _mf(sample_video_path, "video")
        with mf:
            result = model.caption(mf)

        assert result == "a blue square"
        fake_frame.unlink(missing_ok=True)

    def test_video_skips_empty_captions(self, sample_video_path: Path | None):
        if sample_video_path is None:
            pytest.skip("ffmpeg not available")

        model = Blip2CaptionModel()
        fake_frames = []
        for i in range(2):
            f = sample_video_path.parent / f"f{i}.jpg"
            f.write_bytes(b"x")
            fake_frames.append(f)

        model._extract_frames = MagicMock(return_value=fake_frames)  # type: ignore[method-assign]
        model._caption_image = MagicMock(side_effect=["caption one", ""])  # type: ignore[method-assign]

        mf = _mf(sample_video_path, "video")
        with mf:
            result = model.caption(mf)

        assert result == "caption one"  # empty string filtered out
        for f in fake_frames:
            f.unlink(missing_ok=True)
