import httpx
import pytest


@pytest.mark.anyio
async def test_scalar_api_reference_uses_generated_openapi(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/docs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Scalar.createApiReference" in response.text
    assert '"url": "/openapi.json"' in response.text
    assert '"telemetry": false' in response.text
    assert '"agent": {"disabled": true}' in response.text


@pytest.mark.anyio
async def test_openapi_document_remains_available(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Local Translation Service"
    assert "/docs" not in response.json()["paths"]
