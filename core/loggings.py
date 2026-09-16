import logging
from pathlib import Path
from typing import Any

from core.settings import SETTINGS

MAIN_LOG_FILE = Path(SETTINGS.LOG_DIR) / "main.log"
FORMATTER = logging.Formatter(
    "[%(asctime)s.%(msecs)03d000] %(message)s",
    "%Y-%m-%d %H:%M:%S",
)


def main_logger() -> logging.Logger:
    logger = logging.getLogger("log_main")
    if logger.hasHandlers():  # already configured
        return logger

    logger.setLevel(logging.INFO)
    MAIN_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    file_handle = logging.FileHandler(MAIN_LOG_FILE, mode="a")
    file_handle.setFormatter(FORMATTER)
    logger.addHandler(file_handle)

    stream_handle = logging.StreamHandler()
    stream_handle.setFormatter(FORMATTER)
    logger.addHandler(stream_handle)

    return logger


def log_main(message: object, extra: dict[str, Any] | None = None) -> None:
    main_logger().info(message, extra=extra)
