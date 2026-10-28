from fastapi.testclient import TestClient

from runvia.api.app import create_app


def test_live_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "down"}


def test_live_response_schema_is_published_in_openapi() -> None:
    client = TestClient(create_app())

    openapi = client.get("/openapi.json").json()

    response = openapi["paths"]["/health/live"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthStatus"
    }
