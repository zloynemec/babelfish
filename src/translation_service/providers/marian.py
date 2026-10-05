import importlib.util
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol, cast

from translation_service.core.errors import (
    InvalidTranslatorParamsError,
    TranslationFailedError,
    TranslatorUnavailableError,
    UnsupportedLanguagePairError,
)
from translation_service.domain.models import (
    ProviderCapabilities,
    ProviderHealth,
    ProviderTranslationRequest,
    ProviderTranslationResult,
)

MANIFEST_FILENAME = "babelfish-model.json"


@dataclass(frozen=True, slots=True)
class MarianModelSpec:
    source_language: str
    target_language: str
    model_id: str
    root: Path

    @property
    def model_path(self) -> Path:
        return self.root / "model"

    @property
    def tokenizer_path(self) -> Path:
        return self.root / "tokenizer"


class MarianRuntime(Protocol):
    def translate(self, text: str) -> str: ...


ModelDiscovery = Callable[[], Sequence[MarianModelSpec]]
RuntimeLoader = Callable[[MarianModelSpec], MarianRuntime]


def discover_marian_models(models_dir: Path) -> list[MarianModelSpec]:
    if not models_dir.is_dir():
        return []

    models: list[MarianModelSpec] = []
    for manifest_path in sorted(models_dir.glob(f"*/{MANIFEST_FILENAME}")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("provider") != "marian":
                continue
            spec = MarianModelSpec(
                source_language=str(manifest["source_language"]).strip().lower(),
                target_language=str(manifest["target_language"]).strip().lower(),
                model_id=str(manifest["model_id"]),
                root=manifest_path.parent,
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            continue

        if (
            spec.source_language
            and spec.target_language
            and (spec.model_path / "model.bin").is_file()
            and (spec.model_path / "config.json").is_file()
            and spec.tokenizer_path.is_dir()
        ):
            models.append(spec)
    return models


class CTranslate2MarianRuntime:
    def __init__(self, spec: MarianModelSpec, *, device: str, compute_type: str) -> None:
        import ctranslate2
        from transformers import AutoTokenizer

        self._translator = ctranslate2.Translator(
            str(spec.model_path),
            device=device,
            compute_type=compute_type,
        )
        self._tokenizer = AutoTokenizer.from_pretrained(
            spec.tokenizer_path,
            local_files_only=True,
        )

    def translate(self, text: str) -> str:
        token_ids = self._tokenizer.encode(text)
        source_tokens = self._tokenizer.convert_ids_to_tokens(token_ids)
        if not isinstance(source_tokens, list):
            raise RuntimeError("Marian tokenizer returned an invalid token sequence")

        batches = self._translator.translate_batch([source_tokens])
        if not batches or not batches[0].hypotheses:
            raise RuntimeError("CTranslate2 returned no translation hypotheses")

        target_tokens = batches[0].hypotheses[0]
        target_ids = self._tokenizer.convert_tokens_to_ids(target_tokens)
        return cast(
            str,
            self._tokenizer.decode(target_ids, skip_special_tokens=True),
        ).strip()


class MarianProvider:
    """Local MarianMT inference through CTranslate2."""

    name = "marian"

    def __init__(
        self,
        models_dir: Path,
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        model_discovery: ModelDiscovery | None = None,
        runtime_loader: RuntimeLoader | None = None,
    ) -> None:
        self._models_dir = models_dir
        self._device = device
        self._compute_type = compute_type
        self._model_discovery = model_discovery or (
            lambda: discover_marian_models(self._models_dir)
        )
        self._runtime_loader = runtime_loader or self._load_runtime
        self._runtimes: dict[tuple[str, str, Path], MarianRuntime] = {}
        self._runtime_lock = Lock()

    def translate(self, request: ProviderTranslationRequest) -> ProviderTranslationResult:
        if request.params:
            raise InvalidTranslatorParamsError(
                details={
                    "translator": self.name,
                    "unknown_parameters": sorted(request.params),
                }
            )

        try:
            models = list(self._model_discovery())
        except Exception:
            raise TranslatorUnavailableError(details={"translator": self.name}) from None

        spec = next(
            (
                model
                for model in models
                if model.source_language == request.source_language
                and model.target_language == request.target_language
            ),
            None,
        )
        if spec is None:
            details = {
                "translator": self.name,
                "source_language": request.source_language,
                "target_language": request.target_language,
            }
            if not models:
                raise TranslatorUnavailableError(details={"translator": self.name})
            raise UnsupportedLanguagePairError(details=details)

        try:
            runtime = self._get_runtime(spec)
        except Exception:
            raise TranslatorUnavailableError(details={"translator": self.name}) from None

        try:
            translation = runtime.translate(request.text)
        except Exception:
            raise TranslationFailedError(details={"translator": self.name}) from None

        if not translation:
            raise TranslationFailedError(details={"translator": self.name})

        return ProviderTranslationResult(
            translation=translation,
            metadata={"model": spec.model_id},
        )

    def capabilities(self) -> ProviderCapabilities:
        try:
            models = self._model_discovery()
        except Exception:
            models = []
        return ProviderCapabilities(
            supported_pairs=sorted(
                {(model.source_language, model.target_language) for model in models}
            ),
            accepts_params=False,
        )

    def health(self) -> ProviderHealth:
        if importlib.util.find_spec("ctranslate2") is None:
            return ProviderHealth(ready=False, detail="CTranslate2 is unavailable")
        if importlib.util.find_spec("transformers") is None:
            return ProviderHealth(ready=False, detail="Transformers is unavailable")
        try:
            models = self._model_discovery()
        except Exception:
            return ProviderHealth(ready=False, detail="Marian model discovery failed")
        if not models:
            return ProviderHealth(ready=False, detail="No Marian models are installed")
        return ProviderHealth(ready=True)

    def _load_runtime(self, spec: MarianModelSpec) -> MarianRuntime:
        return CTranslate2MarianRuntime(
            spec,
            device=self._device,
            compute_type=self._compute_type,
        )

    def _get_runtime(self, spec: MarianModelSpec) -> MarianRuntime:
        key = (spec.source_language, spec.target_language, spec.root)
        with self._runtime_lock:
            runtime = self._runtimes.get(key)
            if runtime is None:
                runtime = self._runtime_loader(spec)
                self._runtimes[key] = runtime
            return runtime
