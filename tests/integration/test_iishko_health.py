import json

import anyio
import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.main import create_app
from translation_service.providers.iishko import IishkoProvider
from translation_service.services.annotator_registry import AnnotatorRegistry


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("upstream_status", "annotation", "expected_status"),
    [
        (200, "The Moon orbits Earth. Its phases change.", 200),
        (200, "Incomplete", 503),
        (401, "", 503),
    ],
)
async def test_iishko_health_checks_real_annotation_path_once(
    upstream_status: int, annotation: str, expected_status: int
) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            upstream_status, json={"choices": [{"message": {"content": annotation}}]}
        )

    registry = AnnotatorRegistry()
    registry.register(
        IishkoProvider(
            api_key="test-key",
            base_url="https://iishko.test/v1",
            model="test-model",
            timeout_seconds=1,
            transport=httpx.MockTransport(upstream),
        )
    )
    app = create_app(settings=Settings(default_annotator="qwen_local"), annotator_registry=registry)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/health/live")
        assert live.status_code == 200
        assert not requests

        async def check() -> None:
            response = await client.get("/health/iishko")
            assert response.status_code == expected_status
            if expected_status == 200:
                assert response.json() == {"status": "ok"}
            else:
                error = response.json()["error"]
                assert error["code"] == "annotator_unavailable"
                assert error["details"] == {"annotator": "iishko"}
                assert error["request_id"] == response.headers["X-Request-ID"]

        async with anyio.create_task_group() as group:
            group.start_soon(check)
            group.start_soon(check)
        await check()

    [request] = requests
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-key"
    payload = json.loads(request.content)
    assert payload["model"] == "test-model"
    assert "The Moon orbits Earth" in payload["messages"][1]["content"]


@pytest.mark.anyio
async def test_iishko_health_returns_503_when_provider_is_missing() -> None:
    app = create_app(annotator_registry=AnnotatorRegistry())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/iishko")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "annotator_unavailable"
