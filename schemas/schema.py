import enum

from pydantic import BaseModel


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class Segment(BaseModel):
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    language: str
    duration: float
    text: str  # flat transcript (segments joined)
    segments: list[Segment]


class JobCreatedResponse(BaseModel):
    """Returned immediately from POST /transcribe (202 Accepted)."""

    job_id: str
    status: JobStatus


class JobStatusResponse(JobCreatedResponse):
    """Returned from GET /jobs/{job_id}."""

    filename: str | None = None
    language: str | None = None
    duration: float | None = None
    error: str | None = None
