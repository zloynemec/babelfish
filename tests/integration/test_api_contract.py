import time

import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.core.errors import InvalidTranslatorParamsError
from translation_service.domain.models import ProviderTranslationRequest
from translation_service.main import create_app
from translation_service.providers.argos import ArgosProvider
from translation_service.providers.fake import FakeTranslatorProvider
from translation_service.providers.marian import MarianProvider
from translation_service.services.registry import TranslatorRegistry


@pytest.mark.anyio
async def test_minimal_request_uses_defaults_and_returns_metadata(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/v1/translate", json={"text": "Hello", "target_language": "ru"})

    assert response.status_code == 200
    assert response.json() == {
        "translation": "translated:Hello",
        "source_language": "en",
        "target_language": "ru",
        "translator": "fake",
        "metadata": {"duration_ms": response.json()["metadata"]["duration_ms"]},
    }
    assert response.json()["metadata"]["duration_ms"] >= 0
    assert response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_explicit_source_language(settings: Settings) -> None:
    registry = TranslatorRegistry()
    registry.register(
        FakeTranslatorProvider(name="fake", supported_pairs=[("en", "ru"), ("de", "ru")])
    )
    transport = httpx.ASGITransport(app=create_app(settings=settings, registry=registry))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/translate",
            json={"text": "Hallo", "source_language": "de", "target_language": "ru"},
        )

    assert response.status_code == 200
    assert response.json()["source_language"] == "de"


@pytest.mark.anyio
async def test_explicit_translator_is_selected(settings: Settings) -> None:
    registry = TranslatorRegistry()
    registry.register(FakeTranslatorProvider(name="fake"))
    registry.register(
        FakeTranslatorProvider(
            name="second",
            translate_function=lambda request: "second-result",
        )
    )
    transport = httpx.ASGITransport(app=create_app(settings=settings, registry=registry))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/translate",
            json={"text": "Hello", "target_language": "ru", "translator": "SECOND"},
        )

    assert response.status_code == 200
    assert response.json()["translator"] == "second"
    assert response.json()["translation"] == "second-result"


@pytest.mark.anyio
async def test_translator_params_reach_provider(
    client: httpx.AsyncClient, fake_provider: FakeTranslatorProvider
) -> None:
    params = {"style": "short", "nested": {"enabled": True}}

    response = await client.post(
        "/v1/translate",
        json={
            "text": "Hello",
            "target_language": "ru",
            "translator_params": params,
        },
    )

    assert response.status_code == 200
    assert fake_provider.last_request is not None
    assert fake_provider.last_request.params == params


@pytest.mark.anyio
async def test_unknown_translator(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/translate",
        json={"text": "Hello", "target_language": "ru", "translator": "missing"},
    )

    assert_error(response, 404, "unknown_translator")


@pytest.mark.anyio
async def test_unsupported_language_pair(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/translate", json={"text": "Hello", "target_language": "xx"})

    assert_error(response, 422, "unsupported_language_pair")


@pytest.mark.anyio
async def test_provider_unavailable(settings: Settings) -> None:
    registry = TranslatorRegistry()
    registry.register(FakeTranslatorProvider(name="fake", ready=False))
    transport = httpx.ASGITransport(app=create_app(settings=settings, registry=registry))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/translate", json={"text": "Hello", "target_language": "ru"}
        )

    assert_error(response, 503, "translator_unavailable")


@pytest.mark.anyio
async def test_invalid_provider_params(settings: Settings) -> None:
    def reject_params(request: ProviderTranslationRequest) -> str:
        raise InvalidTranslatorParamsError(details={"keys": sorted(request.params)})

    registry = TranslatorRegistry()
    registry.register(FakeTranslatorProvider(name="fake", translate_function=reject_params))
    transport = httpx.ASGITransport(app=create_app(settings=settings, registry=registry))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/translate",
            json={
                "text": "Hello",
                "target_language": "ru",
                "translator_params": {"unknown": True},
            },
        )

    assert_error(response, 422, "invalid_translator_params")


@pytest.mark.anyio
async def test_oversized_text(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/translate", json={"text": "x" * 21, "target_language": "ru"})

    assert_error(response, 413, "text_too_large")


@pytest.mark.anyio
async def test_timeout(settings: Settings) -> None:
    def slow_translate(request: ProviderTranslationRequest) -> str:
        del request
        time.sleep(0.1)
        return "late"

    registry = TranslatorRegistry()
    registry.register(FakeTranslatorProvider(name="fake", translate_function=slow_translate))
    transport = httpx.ASGITransport(app=create_app(settings=settings, registry=registry))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/translate", json={"text": "Hello", "target_language": "ru"}
        )

    assert_error(response, 504, "translation_timeout")


@pytest.mark.anyio
async def test_liveness_succeeds_without_provider() -> None:
    transport = httpx.ASGITransport(app=create_app(registry=TranslatorRegistry()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_readiness_fails_without_default_provider() -> None:
    transport = httpx.ASGITransport(app=create_app(registry=TranslatorRegistry()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert_error(response, 503, "translator_unavailable")


@pytest.mark.anyio
async def test_argos_without_models_is_reported_as_unavailable() -> None:
    registry = TranslatorRegistry()
    registry.register(ArgosProvider(language_loader=lambda: []))
    transport = httpx.ASGITransport(app=create_app(registry=registry))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        translators = await client.get("/v1/translators")
        translation = await client.post(
            "/v1/translate", json={"text": "Hello", "target_language": "ru"}
        )

    assert translators.json() == {
        "translators": [
            {
                "name": "argos",
                "ready": False,
                "supported_language_pairs": [],
            }
        ],
        "default_translator": "argos",
    }
    assert_error(translation, 503, "translator_unavailable")


def test_default_application_registers_production_providers() -> None:
    application = create_app()

    providers = application.state.registry.list()
    assert len(providers) == 2
    assert isinstance(providers[0], ArgosProvider)
    assert isinstance(providers[1], MarianProvider)


@pytest.mark.anyio
async def test_readiness_and_translator_list(
    client: httpx.AsyncClient,
) -> None:
    ready = await client.get("/health/ready")
    translators = await client.get("/v1/translators")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "default_translator": "fake"}
    assert translators.status_code == 200
    assert translators.json() == {
        "translators": [
            {
                "name": "fake",
                "ready": True,
                "supported_language_pairs": [{"source": "en", "target": "ru"}],
            }
        ],
        "default_translator": "fake",
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"target_language": "ru"},
        {"text": "", "target_language": "ru"},
        {"text": "   ", "target_language": "ru"},
        {"text": "Hello", "target_language": "RU"},
        {"text": "Hello", "target_language": "ru", "source_language": None},
        {"text": "Hello", "target_language": "ru", "translator": None},
        {"text": "Hello", "target_language": "ru", "typo": True},
        {"text": "Hello", "target_language": "ru", "translator_params": []},
    ],
)
async def test_invalid_requests_use_common_error_envelope(
    client: httpx.AsyncClient, payload: dict[str, object]
) -> None:
    response = await client.post("/v1/translate", json=payload)

    assert_error(response, 400, "invalid_request")


@pytest.mark.anyio
async def test_provider_exception_does_not_leak_details(settings: Settings) -> None:
    def explode(request: ProviderTranslationRequest) -> str:
        raise RuntimeError(f"secret path /private/model for {request.text}")

    registry = TranslatorRegistry()
    registry.register(FakeTranslatorProvider(name="fake", translate_function=explode))
    transport = httpx.ASGITransport(app=create_app(settings=settings, registry=registry))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/translate", json={"text": "sensitive", "target_language": "ru"}
        )

    assert_error(response, 500, "translation_failed")
    assert "secret" not in response.text
    assert "/private/model" not in response.text
    assert "sensitive" not in response.text


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert isinstance(body["error"]["details"], dict)
    assert isinstance(body["error"]["request_id"], str)
    assert body["error"]["request_id"]
