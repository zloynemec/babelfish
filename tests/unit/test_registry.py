import pytest

from translation_service.core.errors import UnknownTranslatorError
from translation_service.providers.fake import FakeTranslatorProvider
from translation_service.services.registry import (
    DuplicateTranslatorError,
    TranslatorRegistry,
)


def test_register_lookup_list_and_exists_are_case_insensitive() -> None:
    provider = FakeTranslatorProvider(name="Fake")
    registry = TranslatorRegistry()

    registry.register(provider)

    assert registry.get(" fake ") is provider
    assert registry.exists("FAKE") is True
    assert registry.list() == [provider]


def test_duplicate_provider_name_is_rejected() -> None:
    registry = TranslatorRegistry()
    registry.register(FakeTranslatorProvider(name="fake"))

    with pytest.raises(DuplicateTranslatorError):
        registry.register(FakeTranslatorProvider(name="FAKE"))


def test_unknown_provider_uses_public_error() -> None:
    registry = TranslatorRegistry()

    with pytest.raises(UnknownTranslatorError) as error:
        registry.get("missing")

    assert error.value.details == {"translator": "missing"}
