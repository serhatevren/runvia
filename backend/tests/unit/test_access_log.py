from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runvia.api.app import create_app
from runvia.core.config import Settings

type LogReader = Callable[[], list[dict[str, Any]]]


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def _access_entries(read_logs: LogReader) -> list[dict[str, object]]:
    return [e for e in read_logs() if e["logger"] == "runvia.access"]


def test_logs_one_line_per_request(client: TestClient, read_logs: LogReader) -> None:
    response = client.get("/health/live")

    [entry] = _access_entries(read_logs)
    assert entry["message"] == "http_request"
    assert entry["level"] == "info"
    assert entry["method"] == "GET"
    assert entry["path"] == "/health/live"
    assert entry["status_code"] == 200
    assert isinstance(entry["duration_ms"], float)
    assert entry["request_id"] == response.headers["X-Request-ID"]


def test_omits_query_string(client: TestClient, read_logs: LogReader) -> None:
    client.get("/health/live?token=secret-value")

    [entry] = _access_entries(read_logs)
    assert entry["path"] == "/health/live"
    assert "secret-value" not in str(entry)


def test_unhandled_exception_is_logged_as_500_error(
    client: TestClient, read_logs: LogReader
) -> None:
    response = client.get("/_test/boom", headers={"X-Request-ID": "req-boom"})

    assert response.status_code == 500
    [entry] = _access_entries(read_logs)
    assert entry["level"] == "error"
    assert entry["status_code"] == 500
    assert entry["request_id"] == "req-boom"
