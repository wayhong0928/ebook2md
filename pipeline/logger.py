"""
Centralised logging for the pipeline.
Writes to both console (INFO+) and a rotating file (DEBUG+).
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import PIPELINE_DIR

LOG_DIR = PIPELINE_DIR / "logs"
LOG_FILE = LOG_DIR / "pipeline.log"
LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler — INFO and above
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    # File handler — DEBUG and above, 5 MB per file, keep 5 rotations
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
