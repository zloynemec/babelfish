from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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


class AnnotateRequest(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "description": "Exactly one of url, html, or text must be provided.",
            "oneOf": [
                {"required": ["url"]},
                {"required": ["html"]},
                {"required": ["text"]},
            ],
        },
    )

    url: str | None = None
    html: str | None = None
    text: str | None = None
    annotator: str | None = Field(default=None, min_length=1)
    annotator_params: dict[str, Any] = Field(
        default_factory=dict, json_schema_extra={"default": {}}
    )

    @model_validator(mode="after")
    def exactly_one_input(self) -> "AnnotateRequest":
        values = (self.url, self.html, self.text)
        if sum(field in self.model_fields_set for field in ("url", "html", "text")) != 1:
            raise ValueError("exactly one of url, html, text is required")
        if not any(value is not None and value.strip() for value in values):
            raise ValueError("input must not be blank")
        return self


class AnnotationMetadata(StrictModel):
    duration_ms: int = Field(ge=0)
    truncated: bool = False


class AnnotateResponse(StrictModel):
    annotation: str
    language: Literal["ru"]
    annotator: str
    metadata: AnnotationMetadata


class AnnotatorDescriptor(StrictModel):
    name: str
    ready: bool


class AnnotatorListResponse(StrictModel):
    annotators: list[AnnotatorDescriptor]
    default_annotator: str


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status_code: {"model": ErrorEnvelope} for status_code in (400, 404, 413, 422, 500, 503, 504)
}

ANNOTATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status_code: {"model": ErrorEnvelope}
    for status_code in (400, 403, 404, 413, 415, 422, 502, 503, 504)
}
