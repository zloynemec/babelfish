from collections.abc import AsyncIterator

import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.main import create_app
from translation_service.providers.fake import FakeTranslatorProvider
from translation_service.services.registry import TranslatorRegistry


@pytest.fixture
def settings() -> Settings:
    return Settings(
        default_translator="fake",
        default_source_language="en",
        max_text_length=20,
        translation_timeout_seconds=0.05,
    )


@pytest.fixture
def fake_provider() -> FakeTranslatorProvider:
    return FakeTranslatorProvider(name="fake")


@pytest.fixture
def registry(fake_provider: FakeTranslatorProvider) -> TranslatorRegistry:
    result = TranslatorRegistry()
    result.register(fake_provider)
    return result


@pytest.fixture
async def client(
    settings: Settings, registry: TranslatorRegistry
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(settings=settings, registry=registry))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value
