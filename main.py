from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, status

from api.router import router
from core.loggings import log_main
from core.settings import SETTINGS
from manager.storage import BlobStore, InMemoryJobStore
from manager.transcriber import Transcriber


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: build shared resources ONCE before serving traffic.
    app.state.jobs = InMemoryJobStore()
    app.state.blobs = BlobStore(SETTINGS.AUDIO_DIR, SETTINGS.TRANSCRIPT_DIR)
    app.state.transcriber = Transcriber()  # loads the model
    yield
    # Shutdown: release references.
    app.state.transcriber = None


app = FastAPI(
    title="Transcription Pipeline",
    description="Async audio-to-text service with per-segment timestamps.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": status.HTTP_200_OK, "model": SETTINGS.MODEL_SIZE}


if __name__ == "__main__":
    log_main("Starting Main server")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=3000,
        log_level="info",
        workers=1,
        access_log=False,
    )
