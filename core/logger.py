import datetime
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT_DIR / "logs"

# Ensure root logs directory exists immediately
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOG_CATEGORIES = [
    "app",
    "streaming",
    "scrapers",
    "debrid",
    "discover",
    "subtitles",
    "cometnet",
]

_LOG_FORMAT = "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_loggers: Dict[str, logging.Logger] = {}


def get_logs_dir() -> str:
    """Returns absolute path to the root logs directory."""
    return str(LOGS_DIR)


def list_log_files() -> List[str]:
    """Returns a list of all log file names currently in the logs directory."""
    if not LOGS_DIR.exists():
        return []
    return sorted([f.name for f in LOGS_DIR.glob("*.log")])


class AccurateMillisecondFormatter(logging.Formatter):
    """Custom formatter ensuring exact millisecond precision in timestamp."""

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        ct = datetime.datetime.fromtimestamp(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%Y-%m-%d %H:%M:%S")
        return s


def get_logger(category: str = "app", level: int = logging.INFO) -> logging.Logger:
    """
    Returns a configured, thread-safe logger for a specific subsystem.
    Logs are written to both:
    1. logs/{category}_{YYYY-MM-DD}.log (date-stamped)
    2. logs/{category}.log (generic current category log)
    3. Console stream
    """
    category = (category or "app").lower().strip()
    if category in _loggers:
        return _loggers[category]

    logger = logging.getLogger(category)
    logger.setLevel(level)
    logger.propagate = False

    # Avoid duplicate handlers if logger was already created elsewhere
    if not logger.handlers:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        formatter = AccurateMillisecondFormatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        # 1. Dated log file: logs/{category}_{YYYY-MM-DD}.log
        dated_file = LOGS_DIR / f"{category}_{today}.log"
        dated_handler = logging.FileHandler(dated_file, encoding="utf-8")
        dated_handler.setFormatter(formatter)
        dated_handler.setLevel(level)
        logger.addHandler(dated_handler)

        # 2. Main category log file: logs/{category}.log
        generic_file = LOGS_DIR / f"{category}.log"
        generic_handler = logging.FileHandler(generic_file, encoding="utf-8")
        generic_handler.setFormatter(formatter)
        generic_handler.setLevel(level)
        logger.addHandler(generic_handler)

        # 3. Console output stream handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        logger.addHandler(console_handler)

    _loggers[category] = logger
    return logger


# Pre-instantiated primary subsystem loggers for direct import
app_logger = get_logger("app")
streaming_logger = get_logger("streaming")
scrapers_logger = get_logger("scrapers")
debrid_logger = get_logger("debrid")
discover_logger = get_logger("discover")
subtitles_logger = get_logger("subtitles")
cometnet_logger = get_logger("cometnet")
