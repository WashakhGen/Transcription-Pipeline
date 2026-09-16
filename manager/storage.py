import json
from pathlib import Path
from threading import Lock

from schemas.schema import Transcript


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = Lock()

    def save(self, job_id: str, data: dict) -> None:
        with self._lock:
            self._jobs[job_id] = data

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            return self._jobs.get(job_id)


class BlobStore:
    def __init__(self, audio_dir: Path, transcript_dir: Path) -> None:
        self.audio_dir = audio_dir
        self.transcript_dir = transcript_dir
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)

    def audio_path(self, job_id: str) -> Path:
        return self.audio_dir / f"{job_id}.wav"

    def transcript_path(self, job_id: str) -> Path:
        return self.transcript_dir / f"{job_id}.json"

    def save_transcript(self, job_id: str, transcript: Transcript) -> Path:
        dst = self.transcript_path(job_id)
        dst.write_text(transcript.model_dump_json(indent=2))
        return dst

    def get_transcript(self, job_id: str) -> Transcript | None:
        p = self.transcript_path(job_id)
        if not p.exists():
            return None
        return Transcript(**json.loads(p.read_text()))
