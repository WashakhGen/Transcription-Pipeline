from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Storage
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    STORAGE_DIR: Path = BASE_DIR / "storage"
    AUDIO_DIR: Path = STORAGE_DIR / "audio"
    TRANSCRIPT_DIR: Path = STORAGE_DIR / "transcripts"

    # Wisper model
    MODEL_SIZE: str = "base"
    DEVICE: str = "cpu"
    COMPUTE_TYPE: str = "int8"

    # Guards
    MAX_FILE_SIZE_MB: int = 100
    SUPPORTED_FORMATS: set = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}

    # Audio normalization
    TARGET_SAMPLE_RATE: int = 16000
    TARGET_CHANNELS: int = 1

    # Concurrency ---
    MAX_CONCURRENT_JOBS: int = 1

    LOG_DIR: str = "logs"


SETTINGS = Settings()
