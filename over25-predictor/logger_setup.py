"""
Configures logging to both the console and a rotating log file, so a failed
scheduled run can be debugged from the log file alone.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: str, filename: str = "over25_predictor.log") -> logging.Logger:
    out_dir = Path(log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / filename

    logger = logging.getLogger("over25")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger
