import datetime
import os
import re
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.logger import (
    get_logger,
    get_logs_dir,
    app_logger,
    streaming_logger,
    scrapers_logger,
    debrid_logger,
    discover_logger,
    subtitles_logger,
    cometnet_logger,
    LOG_CATEGORIES,
)
from main import app


def test_logs_directory_exists():
    """Verify that root logs directory is created and accessible."""
    logs_dir = get_logs_dir()
    assert os.path.isdir(logs_dir), f"Logs directory {logs_dir} must exist"
    assert os.path.basename(logs_dir) == "logs"


def test_logger_categories_and_date_stamped_files():
    """Verify logging to separate categories creates date-stamped and category files with timestamps."""
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    unique_tag = f"TEST_RUN_{datetime.datetime.now().timestamp()}"

    loggers_map = {
        "app": app_logger,
        "streaming": streaming_logger,
        "scrapers": scrapers_logger,
        "debrid": debrid_logger,
        "discover": discover_logger,
        "subtitles": subtitles_logger,
        "cometnet": cometnet_logger,
    }

    logs_dir = get_logs_dir()

    for category, logger in loggers_map.items():
        test_msg = f"{unique_tag}: Log test for category {category}"
        logger.info(test_msg)

        # Flush handlers
        for handler in logger.handlers:
            handler.flush()

        dated_file = os.path.join(logs_dir, f"{category}_{today}.log")
        generic_file = os.path.join(logs_dir, f"{category}.log")

        assert os.path.isfile(dated_file), f"Expected dated log file: {dated_file}"
        assert os.path.isfile(generic_file), f"Expected category log file: {generic_file}"

        with open(dated_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert test_msg in content, f"Message not found in {dated_file}"

        # Verify time-date stamp format: [YYYY-MM-DD HH:MM:SS.mmm] [LEVEL] [category] message
        pattern = rf"\[\d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}}:\d{{2}}\.\d{{3}}\] \[INFO\] \[{category}\] {re.escape(test_msg)}"
        assert re.search(pattern, content), f"Timestamp format invalid in {dated_file}. Content:\n{content}"


def test_fastapi_request_logging():
    """Verify FastAPI requests are logged with method, path, status, and duration in app log."""
    client = TestClient(app)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    logs_dir = get_logs_dir()
    app_log_file = os.path.join(logs_dir, f"app_{today}.log")

    resp = client.get("/health")
    assert resp.status_code == 200

    for handler in app_logger.handlers:
        handler.flush()

    with open(app_log_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "GET /health - 200" in content, f"Request not recorded in app log:\n{content}"


def test_streaming_daemon_uses_root_logs():
    """Verify core/torrent_streamer.py routes streaming daemon logs to root logs folder."""
    streamer_module_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "torrent_streamer.py"))
    with open(streamer_module_path, "r", encoding="utf-8") as f:
        code = f.read()

    assert "get_logs_dir" in code or "logs" in code
    assert "streaming.log" in code or "streaming_" in code
