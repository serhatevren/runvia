import uuid

import pytest
from fastapi.testclient import TestClient

from runvia.api.app import create_app
from runvia.core.request_context import request_id_var


@pytest.fixture
def client() -> TestClient:
    app = create_app()

    @app.get("/_test/request-id")
    async def echo_request_id() -> dict[str, str | None]:
        return {"request_id": request_id_var.get()}

    return TestClient(app)


def test_generates_request_id_when_missing(client: TestClient) -> None:
    response = client.get("/health/live")

    uuid.UUID(response.headers["X-Request-ID"])


def test_reuses_valid_incoming_request_id(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "lb-abc_123.4"})

    assert response.headers["X-Request-ID"] == "lb-abc_123.4"


@pytest.mark.parametrize("bad_id", ["", "has space", "<script>", "a" * 129])
def test_replaces_invalid_incoming_request_id(client: TestClient, bad_id: str) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": bad_id})

    uuid.UUID(response.headers["X-Request-ID"])


def test_handler_sees_same_request_id_as_response(client: TestClient) -> None:
    response = client.get("/_test/request-id")

    assert response.json()["request_id"] == response.headers["X-Request-ID"]
