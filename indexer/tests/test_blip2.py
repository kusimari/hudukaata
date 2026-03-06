"""Tests for Blip2CaptionModel — all heavy deps are mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from indexer.models.blip2 import Blip2CaptionModel
from indexer.scanner import MediaFile


def _make_mf(path: Path, media_type: str) -> MediaFile:
    from typing import Literal, cast

    return MediaFile(
        relative_path=path.name,
        local_path=path,
        media_type=cast(Literal["image", "video", "audio"], media_type),
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
# caption() — image
# ---------------------------------------------------------------------------


class TestCaptionImage:
    def test_caption_image_returns_stripped_string(self, tmp_path):
        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"fake")

        model = Blip2CaptionModel()
        model._processor = MagicMock()
        model._model = MagicMock()

        mock_pil_img = MagicMock()
        mock_pil_cls = MagicMock()
        mock_pil_cls.open.return_value.convert.return_value = mock_pil_img

        model._processor.batch_decode.return_value = ["  a cat sitting  "]
        model._model.generate.return_value = MagicMock()

        mock_torch = MagicMock()
        mock_pil = MagicMock()
        mock_pil.Image = mock_pil_cls

        with patch.dict(
            "sys.modules",
            {"torch": mock_torch, "PIL": mock_pil, "PIL.Image": mock_pil_cls},
        ):
            result = model._caption_image(img_path)

        assert result == "a cat sitting"


# ---------------------------------------------------------------------------
# caption() — video (temp file cleaned up)
# ---------------------------------------------------------------------------


class TestCaptionVideo:
    def test_caption_video_cleans_up_temp_frame(self, tmp_path):
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"fake video")
        mf = _make_mf(video_path, "video")

        temp_frame = tmp_path / "frame.jpg"
        temp_frame.write_bytes(b"fake frame")

        model = Blip2CaptionModel()

        with (
            patch.object(model, "_extract_middle_frame", return_value=temp_frame),
            patch.object(model, "_caption_image", return_value="a dog running"),
        ):
            result = model.caption(mf)

        assert result == "a dog running"
        # Temp frame must have been deleted
        assert not temp_frame.exists()

    def test_caption_video_cleans_up_even_on_exception(self, tmp_path):
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"fake video")
        mf = _make_mf(video_path, "video")

        temp_frame = tmp_path / "frame.jpg"
        temp_frame.write_bytes(b"fake frame")

        model = Blip2CaptionModel()

        with (
            patch.object(model, "_extract_middle_frame", return_value=temp_frame),
            patch.object(model, "_caption_image", side_effect=RuntimeError("GPU OOM")),
            pytest.raises(RuntimeError, match="GPU OOM"),
        ):
            model.caption(mf)

        assert not temp_frame.exists()


# ---------------------------------------------------------------------------
# caption() — audio
# ---------------------------------------------------------------------------


class TestCaptionAudio:
    def test_caption_audio_returns_transcription(self, tmp_path):
        audio_path = tmp_path / "song.mp3"
        audio_path.write_bytes(b"fake audio")
        mf = _make_mf(audio_path, "audio")

        model = Blip2CaptionModel()
        model._whisper = MagicMock()
        model._whisper.transcribe.return_value = {"text": "  hello world  "}

        result = model.caption(mf)

        assert result == "hello world"
        model._whisper.transcribe.assert_called_once_with(str(audio_path))


# ---------------------------------------------------------------------------
# caption() — unknown media type
# ---------------------------------------------------------------------------


class TestCaptionUnknown:
    def test_returns_empty_string_for_unknown_type(self, tmp_path):
        path = tmp_path / "file.xyz"
        path.write_bytes(b"data")
        # Construct MediaFile directly with a cast to satisfy the Literal type.
        from typing import Literal, cast

        mf = MediaFile(
            relative_path="file.xyz",
            local_path=path,
            media_type=cast(Literal["image", "video", "audio"], "image"),
        )
        model = Blip2CaptionModel()
        # Monkeypatch media_type to trigger the fallback branch
        object.__setattr__(mf, "media_type", "unknown")  # type: ignore[arg-type]

        result = model.caption(mf)  # type: ignore[arg-type]

        assert result == ""


# ---------------------------------------------------------------------------
# _extract_middle_frame — ffprobe warning on failure
# ---------------------------------------------------------------------------


class TestExtractMiddleFrame:
    def test_logs_warning_when_ffprobe_fails(self, tmp_path, caplog):
        import logging

        video_path = tmp_path / "vid.mp4"
        video_path.write_bytes(b"fake")
        model = Blip2CaptionModel()

        mock_run = MagicMock()
        # ffprobe fails, ffmpeg succeeds
        mock_run.side_effect = [
            Exception("ffprobe not found"),
            MagicMock(returncode=0),
        ]

        import contextlib

        with (
            patch("indexer.models.blip2.subprocess.run", mock_run),
            caplog.at_level(logging.WARNING, logger="indexer.models.blip2"),
            contextlib.suppress(Exception),
        ):
            model._extract_middle_frame(video_path)

        assert any("ffprobe failed" in r.message for r in caplog.records)
