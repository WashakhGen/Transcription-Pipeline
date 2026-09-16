import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from api.bg_functions import process_job
from core.loggings import log_main
from manager.storage import BlobStore, InMemoryJobStore
from manager.transcriber import Transcriber
from schemas.media import AudioUpload, MediaBytes
from schemas.schema import (
    JobCreatedResponse,
    JobStatus,
    JobStatusResponse,
    Transcript,
)

router = APIRouter()


def get_jobs(request: Request) -> InMemoryJobStore:
    return request.app.state.jobs


def get_blobs(request: Request) -> BlobStore:
    return request.app.state.blobs


def get_transcriber(request: Request) -> Transcriber:
    return request.app.state.transcriber


@router.post(
    "/transcribe",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_transcription(
    request: Request,
    background_tasks: BackgroundTasks,
    file: AudioUpload,
):
    """Accept audio, store it, enqueue transcription, return a job_id at once."""
    log_main("-------------- Starting Task --------------")
    log_main("Received transcription request")
    jobs = get_jobs(request)
    blobs = get_blobs(request)
    transcriber = get_transcriber(request)

    raw = await file.read()
    try:
        audio = MediaBytes(raw)
    except (MediaBytes.NoAudio, RuntimeError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)) from e

    job_id = str(uuid.uuid4())
    log_main(f"JobUUID: {job_id}  ")

    # Cheap work only: normalize + persist the audio, create the job record.
    log_main("Normalizing audio to wav")
    audio.to_wav(blobs.audio_path(job_id))
    jobs.save(
        job_id,
        {
            "job_id": job_id,
            "status": JobStatus.QUEUED,
            "filename": file.filename,
        },
    )

    background_tasks.add_task(process_job, job_id, jobs, blobs, transcriber)

    return JobCreatedResponse(job_id=job_id, status=JobStatus.QUEUED)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, request: Request):
    job = get_jobs(request).get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobStatusResponse(**job)


@router.get("/jobs/{job_id}/transcript", response_model=Transcript)
async def get_transcript(job_id: str, request: Request):
    jobs = get_jobs(request)
    blobs = get_blobs(request)

    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if job["status"] == JobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=job.get("error", "Job failed"),
        )
    if job["status"] != JobStatus.DONE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Not ready (status: {job['status']})",
        )

    transcript = blobs.get_transcript(job_id)
    if not transcript:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found")
    return transcript
