import json
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import File, UploadFile
from pydantic import AfterValidator, RootModel

from core.settings import SETTINGS

FFPROBE_BIN = "ffprobe"
FFMPEG_BIN = "ffmpeg"


class MediaBytes(RootModel):
    root: bytes

    class NoAudio(Exception): ...

    def model_post_init(self, _: Any, /) -> None:
        # Probe eagerly so invalid/non-audio input is rejected at validation time.
        _assert_has_audio(self.root)

    def to_wav(self, dst: Path) -> Path:
        # Normalize this audio to 16kHz mono PCM WAV for the model.

        with tempfile.NamedTemporaryFile(dir=None) as tmp:
            tmp.write(self.root)
            tmp.flush()
            cmd = [
                FFMPEG_BIN,
                "-y",
                "-i",
                tmp.name,
                "-ar",
                str(SETTINGS.TARGET_SAMPLE_RATE),  # -> 16000
                "-ac",
                str(SETTINGS.TARGET_CHANNELS),  # -> mono
                "-c:a",
                "pcm_s16le",  # standard WAV
                str(dst),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if proc.returncode != 0:
            raise RuntimeError(f"Normalization failed: {proc.stderr[-300:]}")
        return dst


def _assert_has_audio(media_bytes: bytes) -> None:
    """Probe raw bytes with ffprobe; raise if there's no decodable audio stream."""
    with tempfile.NamedTemporaryFile(dir=None) as tmp:  # None for MacOS /tmp dir
        tmp.write(media_bytes)
        tmp.flush()
        cmd = [
            FFPROBE_BIN,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            tmp.name,
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.decode()}")

    data = json.loads(stdout)
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    if not has_audio:
        raise MediaBytes.NoAudio("File contains no decodable audio stream.")


def _validate_audio_upload(file: UploadFile) -> UploadFile:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SETTINGS.SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format {ext or '(none)'}; "
            f"expected one of {sorted(SETTINGS.SUPPORTED_FORMATS)}"
        )

    max_bytes = SETTINGS.MAX_FILE_SIZE_MB * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        raise ValueError(f"File too large ({file.size} bytes); max {SETTINGS.MAX_FILE_SIZE_MB}MB")

    return file


AudioUpload = Annotated[UploadFile, File(...), AfterValidator(_validate_audio_upload)]
