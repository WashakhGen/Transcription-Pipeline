import logging
from threading import Semaphore

from core.loggings import log_main
from core.settings import SETTINGS
from manager.storage import BlobStore, InMemoryJobStore
from manager.transcriber import Transcriber
from schemas.schema import JobStatus

# Caps how many transcriptions run at once. Excess jobs wait here instead of overwhelming CPU/memory
_slots = Semaphore(SETTINGS.MAX_CONCURRENT_JOBS)
logger = logging.getLogger(__name__)


def process_job(
    job_id: str,
    jobs: InMemoryJobStore,
    blobs: BlobStore,
    transcriber: Transcriber,
) -> None:
    """Run one job end-to-end: transcribe -> store transcript -> update status."""
    with _slots:  # blocks if all slots are busy (backpressure)
        try:
            jobs.update(job_id, status=JobStatus.PROCESSING)
            log_main(f"started transcription for job {job_id}")
            transcript = transcriber.transcribe(blobs.audio_path(job_id))
            blobs.save_transcript(job_id, transcript)

            jobs.update(
                job_id,
                status=JobStatus.DONE,
                language=transcript.language,
                duration=transcript.duration,
            )
            log_main(f"------Completed Request for job {job_id}------")
        except Exception as e:
            # One bad job fails it never takes down the service.
            logger.exception("Job %s failed", job_id)
            jobs.update(job_id, status=JobStatus.FAILED, error=str(e))
