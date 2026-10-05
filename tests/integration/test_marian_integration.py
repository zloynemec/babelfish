import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.main import create_app
from translation_service.providers.marian import MarianProvider
from translation_service.services.registry import TranslatorRegistry


@pytest.mark.marian_integration
@pytest.mark.anyio
async def test_marian_translates_en_to_ru_over_http_when_model_is_installed() -> None:
    settings = Settings()
    provider = MarianProvider(
        settings.marian_models_dir,
        device=settings.marian_device,
        compute_type=settings.marian_compute_type,
    )
    if ("en", "ru") not in (provider.capabilities().supported_pairs or []):
        pytest.skip("Marian en -> ru model is not installed")

    registry = TranslatorRegistry()
    registry.register(provider)
    application = create_app(settings=Settings(default_translator="marian"), registry=registry)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/translate",
            json={"text": "Hello world", "target_language": "ru"},
        )

    assert response.status_code == 200
    assert response.json()["translation"].strip()
    assert response.json()["translator"] == "marian"
