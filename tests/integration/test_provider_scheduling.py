from threading import Event

import anyio
import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.domain.annotation import (
    AnnotatorHealth,
    ProviderAnnotationRequest,
    ProviderAnnotationResult,
)
from translation_service.domain.models import ProviderHealth
from translation_service.main import create_app
from translation_service.providers.fake import FakeTranslatorProvider
from translation_service.services.annotation import AnnotationService
from translation_service.services.annotator_registry import AnnotatorRegistry
from translation_service.services.registry import TranslatorRegistry


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/health/ready", "/v1/translators", "/v1/annotators"])
async def test_slow_health_does_not_block_liveness(path: str) -> None:
    started = Event()
    release = Event()

    def health() -> ProviderHealth:
        started.set()
        release.wait(2)
        return ProviderHealth(ready=True)

    class SlowProvider(FakeTranslatorProvider):
        def health(self) -> ProviderHealth:
            return health()

    registry = TranslatorRegistry()
    registry.register(SlowProvider())
    app = create_app(settings=Settings(default_translator="fake"), registry=registry)
    if path == "/v1/annotators":
        annotators = AnnotatorRegistry()
        annotators.register(SlowProvider())
        app.state.annotator_registry = annotators
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        async def slow_request() -> None:
            await client.get(path)

        async with anyio.create_task_group() as group:
            group.start_soon(slow_request)
            try:
                with anyio.fail_after(1):
                    while not started.is_set():
                        await anyio.sleep(0.001)
                    response = await client.get("/health/live")
                    assert response.status_code == 200
                    assert not release.is_set()
            finally:
                release.set()


@pytest.mark.anyio
@pytest.mark.parametrize("inject_service", [False, True])
async def test_translation_and_annotation_share_capacity_after_timeout(inject_service: bool) -> None:
    started = Event()
    release = Event()
    annotation_calls: list[str] = []

    def translate(request) -> str:
        started.set()
        assert release.wait(2)
        return "translated"

    class Annotator:
        name = "fake"

        def health(self) -> AnnotatorHealth:
            annotation_calls.append("health")
            return AnnotatorHealth(ready=True)

        def annotate(self, request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
            annotation_calls.append("annotate")
            return ProviderAnnotationResult(annotation="Первое. Второе.")

    registry = TranslatorRegistry()
    registry.register(FakeTranslatorProvider(translate_function=translate))
    annotators = AnnotatorRegistry()
    annotators.register(Annotator())
    settings = Settings(
        default_translator="fake",
        default_annotator="fake",
        max_concurrent_operations=1,
        translation_timeout_seconds=0.05,
        annotation_timeout_seconds=0.05,
    )
    service = AnnotationService(annotators, settings) if inject_service else None
    app = create_app(
        settings=settings,
        registry=registry,
        annotator_registry=annotators,
        annotation_service=service,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            first = await client.post(
                "/v1/translate", json={"text": "Hello", "target_language": "ru"}
            )
            assert first.json()["error"]["code"] == "translation_timeout"
            assert started.is_set()
            second = await client.post("/v1/annotate", json={"text": "Hello"})
            assert second.json()["error"]["code"] == "annotation_timeout"
            assert annotation_calls == []
            listed = await client.get("/v1/translators")
            assert listed.json()["translators"][0]["ready"] is False
        finally:
            release.set()
            with anyio.fail_after(2):
                await app.state.workers.run(lambda: None)
        response = await client.post("/v1/annotate", json={"text": "Hello"})
        assert response.status_code == 200
        assert annotation_calls == ["health", "annotate"]


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["health", "capabilities"])
async def test_translation_timeout_includes_provider_checks(stage: str) -> None:
    release = Event()
    started = Event()

    def block() -> None:
        started.set()
        assert release.wait(2)

    class Provider(FakeTranslatorProvider):
        def health(self) -> ProviderHealth:
            if stage == "health":
                block()
            return super().health()

        def capabilities(self):
            if stage == "capabilities":
                block()
            return super().capabilities()

    provider = Provider()
    registry = TranslatorRegistry()
    registry.register(provider)
    app = create_app(
        settings=Settings(
            default_translator="fake",
            translation_timeout_seconds=0.05,
            max_concurrent_operations=1,
        ),
        registry=registry,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            response = await client.post(
                "/v1/translate", json={"text": "Hello", "target_language": "ru"}
            )
            assert response.status_code == 504
            assert started.is_set()
            assert provider.last_request is None
        finally:
            release.set()
            with anyio.fail_after(2):
                await app.state.workers.run(lambda: None)
        assert provider.last_request is None


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["prepare", "health"])
async def test_annotation_does_not_start_inference_after_timeout(stage: str) -> None:
    release = Event()
    started = Event()
    calls: list[str] = []

    def block() -> None:
        started.set()
        assert release.wait(2)

    class Annotator:
        name = "fake"

        def health(self) -> AnnotatorHealth:
            calls.append("health")
            if stage == "health":
                block()
            return AnnotatorHealth(ready=True)

        def annotate(self, request: ProviderAnnotationRequest) -> ProviderAnnotationResult:
            calls.append("annotate")
            return ProviderAnnotationResult(annotation="Первое. Второе.")

    class Service(AnnotationService):
        def _prepare(self, *, url: str | None, html: str | None, text: str | None) -> tuple[str, bool]:
            if stage == "prepare":
                block()
            return "Hello", False

    settings = Settings(
        default_annotator="fake", annotation_timeout_seconds=0.05, max_concurrent_operations=1
    )
    annotators = AnnotatorRegistry()
    annotators.register(Annotator())
    app = create_app(
        settings=settings,
        annotator_registry=annotators,
        annotation_service=Service(annotators, settings),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            response = await client.post("/v1/annotate", json={"text": "Hello"})
            assert response.status_code == 504
            assert started.is_set()
        finally:
            release.set()
            with anyio.fail_after(2):
                await app.state.workers.run(lambda: None)
    assert calls == ([] if stage == "prepare" else ["health"])
