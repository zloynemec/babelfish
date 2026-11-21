import anyio
import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.main import create_app
from translation_service.providers.fake import FakeTranslatorProvider
from translation_service.providers.iishko import IishkoProvider
from translation_service.providers.qwen_local import QwenLocalProvider
from translation_service.services.annotator_registry import AnnotatorRegistry
from translation_service.services.registry import TranslatorRegistry


@pytest.mark.anyio
@pytest.mark.parametrize("translator_ready", [True, False])
@pytest.mark.parametrize(
    ("upstream_status", "upstream_body", "iishko_ready"),
    [
        (200, {"data": [{"id": "test-model"}]}, True),
        (200, {"unexpected": []}, False),
        (401, {"error": {}}, False),
    ],
)
async def test_iishko_health_queries_authenticated_model_list_once(
    upstream_status: int,
    upstream_body: dict[str, object],
    iishko_ready: bool,
    translator_ready: bool,
) -> None:
    requests: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(upstream_status, json=upstream_body)

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
    registry.register(
        QwenLocalProvider(
            base_url="http://qwen.test/v1",
            model="test-model",
            timeout_seconds=1,
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        )
    )
    translators = TranslatorRegistry()
    translators.register(FakeTranslatorProvider(ready=translator_ready))
    translators.register(FakeTranslatorProvider(name="marian", ready=False))
    translators.register(FakeTranslatorProvider(name="iishko"))
    app = create_app(
        settings=Settings(default_annotator="qwen_local", default_translator="fake"),
        annotator_registry=registry,
        registry=translators,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/openapi.json")
        assert live.status_code == 200
        assert not requests

        async def check() -> None:
            response = await client.get("/health")
            assert response.status_code == (200 if translator_ready else 503)
            status = ("ok" if iishko_ready else "degraded") if translator_ready else "not_ready"
            assert response.json() == {
                "status": status,
                "checks": {
                    "live": True,
                    "translator": {"name": "fake", "ready": translator_ready},
                    "iishko": iishko_ready,
                    "translators": [
                        {"name": "fake", "ready": translator_ready},
                        {"name": "marian", "ready": False},
                        {"name": "iishko", "ready": iishko_ready},
                    ],
                    "annotators": [
                        {"name": "iishko", "ready": iishko_ready},
                        {"name": "qwen_local", "ready": True},
                    ],
                },
            }

        async with anyio.create_task_group() as group:
            group.start_soon(check)
            group.start_soon(check)
        await check()

    [request] = requests
    assert request.method == "GET"
    assert request.url.path == "/v1/models"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.content == b""


@pytest.mark.anyio
async def test_health_reports_degraded_when_iishko_is_missing(registry: TranslatorRegistry) -> None:
    app = create_app(
        settings=Settings(default_translator="fake"),
        registry=registry,
        annotator_registry=AnnotatorRegistry(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["iishko"] is False
