import logging
from collections.abc import Callable
from typing import Any

import pytest
import structlog

from runvia.core.config import Settings
from runvia.core.logging import REDACTED, configure_logging
from runvia.core.request_context import request_id_var

type LogReader = Callable[[], list[dict[str, Any]]]


@pytest.fixture(autouse=True)
def _configure(settings: Settings) -> None:
    configure_logging(settings, service="api")


def test_structlog_record_is_one_json_line_with_platform_fields(read_logs: LogReader) -> None:
    structlog.get_logger("runvia.test").info("job_started", job_type="build")

    [entry] = read_logs()
    assert entry["message"] == "job_started"
    assert entry["level"] == "info"
    assert entry["service"] == "api"
    assert entry["logger"] == "runvia.test"
    assert entry["job_type"] == "build"
    assert entry["timestamp"].endswith("Z")


def test_stdlib_record_gets_the_same_fields(read_logs: LogReader) -> None:
    logging.getLogger("uvicorn.error").warning("Shutting down %s", "now")

    [entry] = read_logs()
    assert entry["message"] == "Shutting down now"
    assert entry["level"] == "warning"
    assert entry["service"] == "api"
    assert entry["logger"] == "uvicorn.error"
    assert "timestamp" in entry


def test_includes_current_request_id(read_logs: LogReader) -> None:
    token = request_id_var.set("req-123")
    try:
        structlog.get_logger().info("inside_request")
    finally:
        request_id_var.reset(token)
    structlog.get_logger().info("outside_request")

    inside, outside = read_logs()
    assert inside["request_id"] == "req-123"
    assert "request_id" not in outside


def test_redacts_sensitive_keys_at_any_depth(read_logs: LogReader) -> None:
    structlog.get_logger().info(
        "login",
        email="a@example.com",
        password="hunter2",  # noqa: S106
        refresh_token="rt",  # noqa: S106
        headers={"Authorization": "Bearer x", "Accept": "*/*", "set-cookie": "s=1"},
        items=[{"api_key": "k"}],
    )

    [entry] = read_logs()
    assert entry["email"] == "a@example.com"
    assert entry["password"] == REDACTED
    assert entry["refresh_token"] == REDACTED
    assert entry["headers"] == {"Authorization": REDACTED, "Accept": "*/*", "set-cookie": REDACTED}
    assert entry["items"] == [{"api_key": REDACTED}]


def test_exception_is_rendered_as_structured_traceback(read_logs: LogReader) -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        structlog.get_logger().exception("job_failed")

    [entry] = read_logs()
    assert entry["level"] == "error"
    assert entry["exception"][0]["exc_type"] == "ValueError"
    assert entry["exception"][0]["exc_value"] == "boom"


def test_traceback_does_not_include_frame_locals(read_logs: LogReader) -> None:
    def authenticate(password: str) -> None:
        raise ValueError("invalid credentials")

    try:
        authenticate("hunter2")
    except ValueError:
        structlog.get_logger().exception("login_failed")

    assert "hunter2" not in str(read_logs())


def test_drops_records_below_configured_level(read_logs: LogReader) -> None:
    structlog.get_logger().debug("noisy")
    logging.getLogger("some.library").debug("noisy")

    assert read_logs() == []


def test_reconfiguring_does_not_stack_handlers(settings: Settings) -> None:
    configure_logging(settings, service="api")

    names = [h.get_name() for h in logging.getLogger().handlers]
    assert names.count("runvia") == 1
