import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from translation_service.core.errors import (
    InvalidTranslatorParamsError,
    TextTooLargeError,
    TranslationFailedError,
    TranslatorUnavailableError,
    UnsupportedLanguagePairError,
)
from translation_service.domain.models import ProviderTranslationRequest
from translation_service.providers.marian import (
    MANIFEST_FILENAME,
    MarianModelSpec,
    MarianProvider,
    discover_marian_models,
)


@dataclass
class StubRuntime:
    result: str = "Привет"
    error: Exception | None = None

    def translate(self, text: str) -> str:
        assert text == "Hello"
        if self.error is not None:
            raise self.error
        return self.result


def request(**overrides: object) -> ProviderTranslationRequest:
    values = {
        "text": "Hello",
        "source_language": "en",
        "target_language": "ru",
        "params": {},
    }
    values.update(overrides)
    return ProviderTranslationRequest(**values)  # type: ignore[arg-type]


def model_spec(tmp_path: Path) -> MarianModelSpec:
    return MarianModelSpec(
        source_language="en",
        target_language="ru",
        model_id="Helsinki-NLP/opus-mt-en-ru",
        root=tmp_path / "en-ru",
    )


def test_discovers_valid_model_manifests(tmp_path: Path) -> None:
    root = tmp_path / "en-ru"
    (root / "model").mkdir(parents=True)
    (root / "tokenizer").mkdir()
    (root / "model" / "model.bin").touch()
    (root / "model" / "config.json").write_text("{}", encoding="utf-8")
    (root / MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "provider": "marian",
                "source_language": "EN",
                "target_language": "ru",
                "model_id": "example/model",
            }
        ),
        encoding="utf-8",
    )
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / MANIFEST_FILENAME).write_text("not json", encoding="utf-8")

    assert discover_marian_models(tmp_path) == [MarianModelSpec("en", "ru", "example/model", root)]


def test_health_and_capabilities_reflect_installed_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = model_spec(tmp_path)
    monkeypatch.setattr(
        "translation_service.providers.marian.importlib.util.find_spec",
        lambda name: object(),
    )
    provider = MarianProvider(tmp_path, model_discovery=lambda: [spec])

    assert provider.health().ready is True
    assert provider.capabilities().supported_pairs == [("en", "ru")]
    assert provider.capabilities().accepts_params is False


def test_no_installed_model_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "translation_service.providers.marian.importlib.util.find_spec",
        lambda name: object(),
    )
    provider = MarianProvider(tmp_path, model_discovery=lambda: [])

    assert provider.health().ready is False
    assert provider.capabilities().supported_pairs == []
    with pytest.raises(TranslatorUnavailableError):
        provider.translate(request())


def test_supported_pair_is_translated_and_runtime_is_cached(tmp_path: Path) -> None:
    spec = model_spec(tmp_path)
    loads = 0

    def load_runtime(model: MarianModelSpec) -> StubRuntime:
        nonlocal loads
        assert model is spec
        loads += 1
        return StubRuntime()

    provider = MarianProvider(
        tmp_path,
        model_discovery=lambda: [spec],
        runtime_loader=load_runtime,
    )

    first = provider.translate(request())
    second = provider.translate(request())

    assert first.translation == "Привет"
    assert first.metadata == {"model": "Helsinki-NLP/opus-mt-en-ru"}
    assert second.translation == "Привет"
    assert loads == 1


def test_unknown_params_are_rejected(tmp_path: Path) -> None:
    provider = MarianProvider(tmp_path, model_discovery=lambda: [model_spec(tmp_path)])

    with pytest.raises(InvalidTranslatorParamsError):
        provider.translate(request(params={"beam_size": 5}))


def test_unsupported_pair_is_normalized(tmp_path: Path) -> None:
    provider = MarianProvider(tmp_path, model_discovery=lambda: [model_spec(tmp_path)])

    with pytest.raises(UnsupportedLanguagePairError):
        provider.translate(request(target_language="de"))


def test_runtime_load_failure_reports_unavailable(tmp_path: Path) -> None:
    def fail_to_load(model: MarianModelSpec) -> StubRuntime:
        del model
        raise RuntimeError("secret /private/model/path")

    provider = MarianProvider(
        tmp_path,
        model_discovery=lambda: [model_spec(tmp_path)],
        runtime_loader=fail_to_load,
    )

    with pytest.raises(TranslatorUnavailableError) as error:
        provider.translate(request())
    assert "/private/model/path" not in error.value.details.values()


def test_runtime_translation_failure_is_normalized(tmp_path: Path) -> None:
    provider = MarianProvider(
        tmp_path,
        model_discovery=lambda: [model_spec(tmp_path)],
        runtime_loader=lambda model: StubRuntime(error=RuntimeError(str(model.root))),
    )

    with pytest.raises(TranslationFailedError) as error:
        provider.translate(request())
    assert str(tmp_path) not in error.value.details.values()


def test_runtime_token_limit_preserves_public_error(tmp_path: Path) -> None:
    provider = MarianProvider(
        tmp_path,
        model_discovery=lambda: [model_spec(tmp_path)],
        runtime_loader=lambda model: StubRuntime(error=TextTooLargeError()),
    )
    with pytest.raises(TextTooLargeError):
        provider.translate(request())
