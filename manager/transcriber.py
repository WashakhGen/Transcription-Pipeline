from pathlib import Path

from faster_whisper import WhisperModel

from core.loggings import log_main
from core.settings import SETTINGS
from schemas.schema import Segment, Transcript


class Transcriber:
    def __init__(self) -> None:
        log_main(f"Loading Whisper model: {SETTINGS.MODEL_SIZE} on {SETTINGS.DEVICE}")
        self.model = WhisperModel(
            SETTINGS.MODEL_SIZE,
            device=SETTINGS.DEVICE,
            compute_type=SETTINGS.COMPUTE_TYPE,
        )

    def transcribe(self, audio_path: Path) -> Transcript:
        log_main("Transcribing audio ...")
        segments, info = self.model.transcribe(
            str(audio_path),
            beam_size=5,
            vad_filter=True,
        )
        log_main("Transcription completed.")
        seg_list = [
            Segment(start=round(s.start, 2), end=round(s.end, 2), text=s.text.strip())
            for s in segments
        ]

        return Transcript(
            language=info.language,
            duration=round(info.duration, 2),
            text=" ".join(s.text for s in seg_list),
            segments=seg_list,
        )
