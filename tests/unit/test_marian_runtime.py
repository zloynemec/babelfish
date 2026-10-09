import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from translation_service.core.errors import TextTooLargeError, TranslationFailedError
from translation_service.providers.marian import CTranslate2MarianRuntime, MarianModelSpec


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CTranslate2MarianRuntime:
    tokenizer = SimpleNamespace(
        model_max_length=4,
        eos_token="</s>",
        encode=lambda text: list(range(len(text))),
        convert_ids_to_tokens=lambda ids: [str(value) for value in ids],
        convert_tokens_to_ids=lambda tokens: tokens,
        decode=lambda ids, **kwargs: " ".join(token for token in ids if token != "</s>"),
    )

    def translate_batch(sources, **kwargs):
        tokens = sources[0]
        # Emulate the engine's input truncation unless explicitly disabled.
        if kwargs.get("max_input_length", 2):
            tokens = tokens[:2]
        if kwargs.get("return_end_token", False):
            tokens = [*tokens, "</s>"]
        return [SimpleNamespace(hypotheses=[tokens])]

    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        SimpleNamespace(
            Translator=lambda *args, **kwargs: SimpleNamespace(
                translate_batch=translate_batch,
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoTokenizer=SimpleNamespace(
                from_pretrained=lambda *args, **kwargs: tokenizer,
            )
        ),
    )
    return CTranslate2MarianRuntime(
        MarianModelSpec("en", "ru", "test/model", tmp_path),
        device="cpu",
        compute_type="int8",
    )


def test_runtime_rejects_input_over_model_token_limit(runtime: CTranslate2MarianRuntime) -> None:
    with pytest.raises(TextTooLargeError):
        runtime.translate("12345")


def test_runtime_preserves_complete_input_at_limit(runtime: CTranslate2MarianRuntime) -> None:
    assert runtime.translate("1234") == "0 1 2 3"


def test_runtime_rejects_output_without_eos(runtime: CTranslate2MarianRuntime) -> None:
    runtime._translator.translate_batch = lambda *args, **kwargs: [
        SimpleNamespace(hypotheses=[["incomplete"]])
    ]
    with pytest.raises(TranslationFailedError):
        runtime.translate("123")
