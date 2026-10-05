from pathlib import Path

import yaml

from translation_service.core.config import Settings
from translation_service.main import create_app
from translation_service.providers.fake import FakeTranslatorProvider
from translation_service.services.registry import TranslatorRegistry


def test_generated_openapi_contains_documented_contract() -> None:
    registry = TranslatorRegistry()
    registry.register(FakeTranslatorProvider(name="fake"))
    schema = create_app(settings=Settings(default_translator="fake"), registry=registry).openapi()

    project_root = Path(__file__).parents[2]
    documented = yaml.safe_load((project_root / "openapi.yaml").read_text(encoding="utf-8"))

    assert set(schema["paths"]) == set(documented["paths"])
    for path, documented_path in documented["paths"].items():
        assert set(schema["paths"][path]) == set(documented_path)
        for method, documented_operation in documented_path.items():
            generated_operation = schema["paths"][path][method]
            assert generated_operation["operationId"] == documented_operation["operationId"]
            assert set(generated_operation["responses"]) == set(documented_operation["responses"])

    translate = schema["paths"]["/v1/translate"]["post"]
    assert translate["operationId"] == "translateText"
    assert set(translate["responses"]) == {
        "200",
        "400",
        "404",
        "413",
        "422",
        "500",
        "503",
        "504",
    }

    request_schema = schema["components"]["schemas"]["TranslateRequest"]
    assert request_schema["required"] == ["text", "target_language"]
    assert request_schema["additionalProperties"] is False
    assert request_schema["properties"]["translator_params"] == {
        "additionalProperties": True,
        "default": {},
        "title": "Translator Params",
        "type": "object",
    }

    annotate_schema = schema["components"]["schemas"]["AnnotateRequest"]
    assert annotate_schema["additionalProperties"] is False
    assert annotate_schema["oneOf"] == [
        {"required": ["url"]},
        {"required": ["html"]},
        {"required": ["text"]},
    ]
    assert annotate_schema["properties"]["annotator_params"]["default"] == {}

    response_schema = schema["components"]["schemas"]["TranslateResponse"]
    assert set(response_schema["required"]) == {
        "translation",
        "source_language",
        "target_language",
        "translator",
        "metadata",
    }

    live_schema = schema["components"]["schemas"]["LiveResponse"]
    ready_schema = schema["components"]["schemas"]["ReadyResponse"]
    assert live_schema["required"] == ["status"]
    assert live_schema["properties"]["status"]["const"] == "ok"
    assert set(ready_schema["required"]) == {"status", "default_translator"}
    assert ready_schema["properties"]["status"]["const"] == "ready"
