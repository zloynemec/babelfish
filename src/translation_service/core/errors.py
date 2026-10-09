from collections.abc import Mapping
from typing import Any


class ApplicationError(Exception):
    """A safe, public application error."""

    code = "application_error"
    status_code = 500
    default_message = "Application error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = dict(details or {})
        super().__init__(self.message)


class InvalidRequestError(ApplicationError):
    code = "invalid_request"
    status_code = 400
    default_message = "Request is invalid"


class TextTooLargeError(ApplicationError):
    code = "text_too_large"
    status_code = 413
    default_message = "Text exceeds the configured maximum length"


class RequestBodyTooLargeError(ApplicationError):
    code = "request_body_too_large"
    status_code = 413
    default_message = "Request body exceeds the configured maximum size"


class UnknownTranslatorError(ApplicationError):
    code = "unknown_translator"
    status_code = 404
    default_message = "Translator is not registered"


class InvalidTranslatorParamsError(ApplicationError):
    code = "invalid_translator_params"
    status_code = 422
    default_message = "Translator parameters are invalid"


class UnsupportedLanguagePairError(ApplicationError):
    code = "unsupported_language_pair"
    status_code = 422
    default_message = "Translator does not support requested language pair"


class TranslatorUnavailableError(ApplicationError):
    code = "translator_unavailable"
    status_code = 503
    default_message = "Translator is not ready"


class TranslationTimeoutError(ApplicationError):
    code = "translation_timeout"
    status_code = 504
    default_message = "Translation timed out"


class TranslationFailedError(ApplicationError):
    code = "translation_failed"
    status_code = 500
    default_message = "Translation failed"


class UrlNotAllowedError(ApplicationError):
    code = "url_not_allowed"
    status_code = 403
    default_message = "URL is not allowed"


class ContentTooLargeError(ApplicationError):
    code = "content_too_large"
    status_code = 413
    default_message = "Content exceeds the configured maximum length"


class UnsupportedContentTypeError(ApplicationError):
    code = "unsupported_content_type"
    status_code = 415
    default_message = "Content type is not supported"


class ContentNotExtractableError(ApplicationError):
    code = "content_not_extractable"
    status_code = 422
    default_message = "Content has no extractable text"


class InvalidAnnotatorParamsError(ApplicationError):
    code = "invalid_annotator_params"
    status_code = 422
    default_message = "Annotator parameters are invalid"


class UnknownAnnotatorError(ApplicationError):
    code = "unknown_annotator"
    status_code = 404
    default_message = "Annotator is not registered"


class ContentFetchFailedError(ApplicationError):
    code = "content_fetch_failed"
    status_code = 502
    default_message = "Content could not be fetched"


class AnnotationFailedError(ApplicationError):
    code = "annotation_failed"
    status_code = 502
    default_message = "Annotation failed"


class AnnotatorUnavailableError(ApplicationError):
    code = "annotator_unavailable"
    status_code = 503
    default_message = "Annotator is unavailable"


class AnnotationTimeoutError(ApplicationError):
    code = "annotation_timeout"
    status_code = 504
    default_message = "Annotation timed out"
