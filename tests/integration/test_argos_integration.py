import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.main import create_app
from translation_service.providers.argos import ArgosProvider
from translation_service.services.registry import TranslatorRegistry


@pytest.mark.argos_integration
@pytest.mark.anyio
async def test_argos_translates_en_to_ru_over_http_when_model_is_installed() -> None:
    provider = ArgosProvider()
    health = provider.health()
    if not health.ready:
        pytest.skip("No Argos translation models are installed")
    if ("en", "ru") not in (provider.capabilities().supported_pairs or []):
        pytest.skip("Argos en -> ru model is not installed")

    registry = TranslatorRegistry()
    registry.register(provider)
    application = create_app(settings=Settings(default_translator="argos"), registry=registry)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/translate",
            json={"text": "Hello world", "target_language": "ru"},
        )

    assert response.status_code == 200
    assert response.json()["translation"].strip()
    assert response.json()["translator"] == "argos"
