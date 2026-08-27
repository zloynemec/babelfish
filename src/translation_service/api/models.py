from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

LanguageCode = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]+)*$"),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranslateRequest(StrictModel):
    text: str = Field(min_length=1)
    target_language: LanguageCode
    source_language: LanguageCode = Field(default=None)  # type: ignore[assignment]
    translator: str = Field(default=None, min_length=1)  # type: ignore[assignment]
    translator_params: dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"default": {}},
    )


class TranslationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    duration_ms: int = Field(ge=0)


class TranslateResponse(StrictModel):
    translation: str
    source_language: LanguageCode
    target_language: LanguageCode
    translator: str
    metadata: TranslationMetadata


class LanguagePair(StrictModel):
    source: LanguageCode
    target: LanguageCode


class TranslatorDescriptor(StrictModel):
    name: str
    ready: bool
    supported_language_pairs: list[LanguagePair] | None


class TranslatorListResponse(StrictModel):
    translators: list[TranslatorDescriptor]
    default_translator: str


class LiveResponse(StrictModel):
    status: Literal["ok"]


class ReadyResponse(StrictModel):
    status: Literal["ready"]
    default_translator: str


class ErrorBody(StrictModel):
    code: str
    message: str
    details: dict[str, Any]
    request_id: str


class ErrorEnvelope(StrictModel):
    error: ErrorBody


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status_code: {"model": ErrorEnvelope} for status_code in (400, 404, 413, 422, 500, 503, 504)
}
