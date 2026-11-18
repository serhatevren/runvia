from fastapi.testclient import TestClient

from runvia.api.app import create_app
from runvia.core.config import Settings


def test_live_returns_ok(settings: Settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_live_response_schema_is_published_in_openapi(settings: Settings) -> None:
    client = TestClient(create_app(settings))

    openapi = client.get("/openapi.json").json()

    response = openapi["paths"]["/health/live"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthStatus"
    }
