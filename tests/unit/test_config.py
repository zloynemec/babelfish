from pathlib import Path

from pytest import MonkeyPatch

from translation_service.core.config import Settings


def test_config_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_host == "0.0.0.0"
    assert settings.app_port == 8000
    assert settings.default_translator == "argos"
    assert settings.default_source_language == "en"
    assert settings.max_text_length == 20_000
    assert settings.max_request_body_bytes == 16_000_000
    assert settings.max_concurrent_operations == 4
    assert settings.translation_timeout_seconds == 30
    assert settings.marian_models_dir.name == "marian"
    assert settings.marian_device == "cpu"
    assert settings.marian_compute_type == "int8"


def test_config_loads_and_normalizes_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_TRANSLATOR", " FAKE ")
    monkeypatch.setenv("DEFAULT_SOURCE_LANGUAGE", "DE")
    monkeypatch.setenv("MAX_TEXT_LENGTH", "123")
    monkeypatch.setenv("MARIAN_MODELS_DIR", "~/models/marian")
    monkeypatch.setenv("MARIAN_COMPUTE_TYPE", " FLOAT32 ")

    settings = Settings(_env_file=None)

    assert settings.default_translator == "fake"
    assert settings.default_source_language == "de"
    assert settings.max_text_length == 123
    assert settings.marian_models_dir == Path.home() / "models" / "marian"
    assert settings.marian_compute_type == "float32"
