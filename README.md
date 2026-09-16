# Transcription Pipeline

An async, job-based REST API that turns an uploaded audio file into a timestamped transcript. Built as a take-home exercise; this README leads with *why* the pipeline is built this way, not just what it does, since the brief asked for engineering reasoning over model accuracy.

## Pipeline flow

```
audio file (multipart upload)
        │
        ▼
  intake & validation        cheap checks first: extension + size (before the file
  (schemas/media.py)         is even fully handled), then ffprobe confirms it's
        │                    genuinely decodable audio, not just a correctly-named file
        ▼
  normalize to 16kHz          ffmpeg -> mono PCM WAV, one canonical format regardless
  mono WAV                    of what came in
        │
        ▼
  202 Accepted + job_id        the client gets a job_id immediately; transcription
  (job enters QUEUED)          hasn't started yet
        │
        ▼
  background worker            faster-whisper transcribes; job moves through
  (api/bg_functions.py)        PROCESSING -> DONE (or FAILED)
        │
        ▼
  client polls
  GET /jobs/{id}                status + metadata
  GET /jobs/{id}/transcript     full text + per-segment timestamps, once DONE
```

## Tech stack

Python 3.12, FastAPI, faster-whisper (CTranslate2), FFmpeg/ffprobe (system dependency), Pydantic v2, uv (dependency management), Ruff + pyright + pre-commit (linting/CI).

## Architecture

| Path | Responsibility |
|---|---|
| `main.py` | FastAPI app, `lifespan` (builds the model + stores once at startup), `/health`, entrypoint |
| `api/router.py` | HTTP layer: `POST /transcribe`, `GET /jobs/{id}`, `GET /jobs/{id}/transcript` |
| `api/bg_functions.py` | Background worker, runs one job end-to-end under the concurrency semaphore |
| `core/settings.py` | Typed, `.env`-driven config (`pydantic-settings`) |
| `core/loggings.py` | Console + file logger, used across the pipeline for job-lifecycle events |
| `manager/storage.py` | `InMemoryJobStore` (job metadata) and `BlobStore` (audio/transcript files on disk) |
| `manager/transcriber.py` | `Transcriber`, loads the faster-whisper model once, runs transcription |
| `schemas/media.py` | `AudioUpload` (upload-level validation: extension + size) and `MediaBytes` (decodability probe + WAV normalization) |
| `schemas/schema.py` | Pydantic models: `JobStatus`, `Segment`, `Transcript`, `JobCreatedResponse`, `JobStatusResponse` |

## Engineering decisions

**1. faster-whisper, running locally.** Chosen over the OpenAI Whisper API (no per-minute cost, no audio leaving the machine, works offline) and over lighter engines like Vosk (Whisper is meaningfully more accurate on accents, background noise, and multilingual audio). faster-whisper specifically because it's a CTranslate2 reimplementation of the same model: roughly 4x faster and lower memory than the reference PyTorch implementation at identical accuracy. The trade-off is that you now host the compute instead of paying a managed API per request, which is the right default whenever cost, privacy, or offline capability matter more than zero ops.

**2. CPU + int8 quantization.** Developed on Apple Silicon (M4 Pro). faster-whisper's engine (CTranslate2) has no Metal/Apple-GPU backend, so on Mac it's CPU-only by construction: `device="cpu"`, `compute_type="int8"` is the correct config here, and the M-series CPU comfortably runs the `base` model faster than real-time. If GPU acceleration on Apple Silicon were needed, the swap is an MLX-Whisper backend; because transcription is isolated behind one class (`Transcriber`), that's a one-file change, not a pipeline rewrite.

**3. Intake is a separate concern from transcription, and validation is two-tiered.** Every upload is validated then normalized to one canonical format (16kHz mono PCM WAV) before it ever reaches the model. Validation happens in two stages, cheapest first: `AudioUpload` (an `Annotated[UploadFile, ...]` type with a pydantic `AfterValidator`) rejects a bad extension or oversized file using only the multipart headers, no bytes decoded yet. Only after that passes does `MediaBytes` run `ffprobe` against the actual bytes to confirm the file is genuinely decodable audio, not just correctly named, catching corrupt or mislabeled uploads before any expensive work runs. `ffmpeg` then does the one-command normalization (it detects the source codec itself, so one code path handles every input format). This split means bad input dies cheaply and early, format handling is testable without ever loading the ML model, and swapping the transcription engine later doesn't touch how files are accepted.

**4. FFmpeg is a system dependency, not a pip package.** `ffmpeg`/`ffprobe` are C binaries, so they can't live in `pyproject.toml`. They're documented here as a local prerequisite (`brew install ffmpeg` / `apt-get install ffmpeg`). Containerizing this service, a Dockerfile that `apt-get install`s ffmpeg alongside the Python deps, is the obvious next step for reproducible deployment, but isn't included in this demo.

**5. Bytes as the internal representation; the API contract is a file upload.** However audio arrives, it reduces to bytes, and the core (`MediaBytes`) only ever operates on bytes: the endpoint's job is just to extract them and hand off. That keeps the core transport-agnostic (swapping the intake mechanism later doesn't touch validation/normalization) and filesystem-agnostic (nothing is written to disk until after validation passes, which makes a later S3 swap clean). The trade-off is that bytes sit fully in memory during validation, which is fine at the file-size cap enforced here (100MB default) but wouldn't be for very large files; those would need to stream to a temp handle instead. Separately, the *external* contract is a multipart file upload, not base64: it's the natural shape for a transcription API, works out of the box with the Swagger `/docs` file picker, and avoids base64's ~33% size overhead on the wire.

**6. Model loaded once, at startup, via FastAPI `lifespan`.** `Transcriber` loads the model weights in `__init__`, and it's instantiated exactly once in `main.py`'s `lifespan` handler, stored on `app.state`, and injected into routes via request-scoped accessors. Loading here, rather than lazily on first request or behind `lru_cache`, means the model is warm before the server accepts any traffic: no cold-start latency spike on whichever request happens to arrive first. Loading weights per-request would dominate runtime and destroy throughput. The worker function (`process_job`) receives the transcriber as a plain argument rather than importing FastAPI itself, so the actual transcription logic stays framework-agnostic and independently testable.

**7. Async job model with `BackgroundTasks`.** Transcription takes seconds to minutes, so a synchronous endpoint would either time out or hold a connection open per concurrent upload. Instead, `POST /transcribe` does only cheap work (validate, normalize, persist the audio, create the job record) and returns `202 Accepted` with a `job_id` immediately; the actual transcription is dispatched as a background task. The client polls `GET /jobs/{id}` for status and `GET /jobs/{id}/transcript` for the result once it's `DONE`. `BackgroundTasks` here is a demo-grade stand-in for the interface a real queue (Redis/SQS + Celery/RQ) would provide: `process_job` doesn't know or care how it was invoked, so only the dispatch line (`add_task(...)` -> `queue.enqueue(...)`) would change to go to production.

**8. Storage is split by how likely each half is to change.** A single job UUID keys everything: the audio blob (`storage/audio/{uuid}.wav`), the transcript blob (`storage/transcripts/{uuid}.json`), and the in-memory job record. `manager/storage.py` has two concrete classes and no interfaces: `InMemoryJobStore` for job metadata and `BlobStore` for files on disk. Neither is hidden behind an abstract base class; with a single implementation each, an interface would be ceremony, not design. An interface is worth adding the moment a second implementation actually shows up (Postgres/Redis for jobs, S3 for blobs), not before. The in-memory store uses a `threading.Lock` because background jobs run in a threadpool and mutate shared state concurrently.

**9. Concurrency capped by a semaphore.** The worker wraps its work in `threading.Semaphore(MAX_CONCURRENT_JOBS)` so a burst of uploads can't thrash CPU or exhaust memory: the in-process stand-in for a fixed worker pool, i.e. backpressure. It's currently set to `1` because the model is CPU-bound on this machine and running several transcriptions in parallel would just make all of them slower rather than increasing throughput. The cap is a config value (`core/settings.py`), so raising it, or moving to multiple worker processes behind a shared queue for real horizontal scaling, needs no code change.

**10. Resilience and observability.** The worker wraps each job in a broad `try/except`: a background task must never fail silently, so any exception marks the job `FAILED` with the error message and logs the full traceback, rather than the job vanishing into the threadpool. One bad job never takes the service down. HTTP status codes are deliberate throughout: `202` (accepted, not yet done), `404` (unknown job or transcript), `409` (job exists but isn't ready), `422` (job failed, or the upload itself was invalid). Key pipeline events (request received, job id issued, normalization, transcription start/finish) are logged to both stdout and `logs/main.log` via `core/loggings.py`; uvicorn's own per-request access log is disabled (`access_log=False`) so output stays focused on pipeline events instead of HTTP noise.

## Handling long audio (design note)

Whisper internally windows audio into 30-second chunks, so long files transcribe correctly with no special handling; `vad_filter=True` additionally skips silence, which is both faster and avoids hallucination during silent stretches. For very long files (hours, not minutes), the scaling approach would be to split the normalized WAV on silence boundaries rather than fixed time (so words are never cut mid-word), transcribe chunks in parallel, and offset each chunk's segment timestamps by its start position when merging. The async worker model already in place is the natural hook for this: chunking would happen inside `process_job` without touching the API contract.

## Engineering hygiene

Every push and PR to `main` runs through GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)): `ruff check`, `ruff format --check`, and `pyright`, against Python 3.12 via `uv`. The same three checks run locally as pre-commit hooks ([`.pre-commit-config.yaml`](.pre-commit-config.yaml)); `ruff --fix` and `ruff-format` auto-correct what they can, `pyright` runs in `basic` mode, so issues are caught before a commit lands, not just in CI.

## Setup

Prerequisite: FFmpeg installed locally.

```bash
brew install ffmpeg        # macOS
# or
apt-get install ffmpeg     # Debian/Ubuntu

ffprobe -version           # verify
```

Install dependencies (this project uses `uv` + `uv.lock`):

```bash
uv sync
```

Run (development, with autoreload):

```bash
uv run uvicorn main:app --reload --port 3000
```

Run (as configured: fixed port, no reload, structured logging to `logs/main.log`):

```bash
uv run main.py
```

Interactive API docs (FastAPI-generated Swagger UI): `http://localhost:3000/docs`

## API reference

**`POST /transcribe`**, multipart form upload, field name `file`. Returns `202 Accepted`:
```json
{ "job_id": "uuid", "status": "queued" }
```
`422` if the file's extension/size fails the upload check, or the bytes aren't decodable audio.

**`GET /jobs/{job_id}`**, current status:
```json
{ "job_id": "uuid", "status": "done", "filename": "clip.mp3", "language": "en", "duration": 12.4, "error": null }
```
`404` if the job doesn't exist.

**`GET /jobs/{job_id}/transcript`**, full transcript, once `DONE`:
```json
{
  "language": "en",
  "duration": 12.4,
  "text": "full flat transcript ...",
  "segments": [{ "start": 0.0, "end": 2.31, "text": "..." }]
}
```
`404` unknown job/transcript, `409` job exists but isn't `DONE` yet, `422` job `FAILED`.

**`GET /health`**: `{ "status": 200, "model": "base" }`

## Configuration

All settings are `.env`-overridable (`core/settings.py`):

| Variable | Default | Purpose |
|---|---|---|
| `MODEL_SIZE` | `base` | faster-whisper model size |
| `DEVICE` / `COMPUTE_TYPE` | `cpu` / `int8` | inference backend |
| `MAX_FILE_SIZE_MB` | `100` | upload size cap |
| `SUPPORTED_FORMATS` | `.wav .mp3 .m4a .flac .ogg .aac` | accepted extensions |
| `TARGET_SAMPLE_RATE` / `TARGET_CHANNELS` | `16000` / `1` | normalization target |
| `MAX_CONCURRENT_JOBS` | `1` | worker semaphore |

## Demo vs. production

This is intentionally a single-process demo, and every corner cut is a named, swappable seam rather than an accident:

- **Job store**: in-memory dict -> Postgres/Redis. `InMemoryJobStore` is the only thing that needs replacing; nothing else references it by concrete type where it matters.
- **Dispatch**: `BackgroundTasks` -> a real queue (Redis/SQS + Celery/RQ). `process_job`'s signature doesn't change.
- **Blob storage**: local disk -> S3. `BlobStore` already only deals in bytes and paths, not framework objects.
- **Concurrency**: one in-process semaphore -> multiple worker processes behind a shared queue, once jobs aren't all fighting for the same CPU.
- **Containerization**: not included; the natural next step is a Dockerfile that installs `ffmpeg` alongside the Python deps so the FFmpeg system-dependency point above disappears in deployment.

