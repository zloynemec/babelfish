from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from scalar_fastapi import AgentScalarConfig, get_scalar_api_reference
from starlette.middleware.base import RequestResponseEndpoint

from translation_service.api.models import ErrorBody, ErrorEnvelope
from translation_service.api.routes_annotate import router as annotate_router
from translation_service.api.routes_health import router as health_router
from translation_service.api.routes_translate import router as translate_router
from translation_service.api.routes_translators import router as translators_router
from translation_service.core.config import Settings
from translation_service.core.errors import (
    ApplicationError,
    InvalidRequestError,
    TranslationFailedError,
)
from translation_service.providers.argos import ArgosProvider
from translation_service.providers.iishko import IishkoProvider
from translation_service.providers.marian import MarianProvider
from translation_service.providers.qwen_local import QwenLocalProvider
from translation_service.services.annotation import AnnotationService
from translation_service.services.annotator_registry import AnnotatorRegistry
from translation_service.services.registry import TranslatorRegistry
from translation_service.services.translation import TranslationService


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


def _error_response(request: Request, error: ApplicationError) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorBody(
            code=error.code,
            message=error.message,
            details=error.details,
            request_id=_request_id(request),
        )
    )
    return JSONResponse(status_code=error.status_code, content=body.model_dump(mode="json"))


def create_app(
    *,
    settings: Settings | None = None,
    registry: TranslatorRegistry | None = None,
    annotator_registry: AnnotatorRegistry | None = None,
    annotation_service: AnnotationService | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    if registry is None:
        resolved_registry = TranslatorRegistry()
        resolved_registry.register(ArgosProvider())
        resolved_registry.register(
            MarianProvider(
                resolved_settings.marian_models_dir,
                device=resolved_settings.marian_device,
                compute_type=resolved_settings.marian_compute_type,
            )
        )
    else:
        resolved_registry = registry

    resolved_annotator_registry = annotator_registry or AnnotatorRegistry()
    if annotator_registry is None:
        resolved_annotator_registry.register(
            IishkoProvider(
                api_key=(
                    resolved_settings.iishko_api_key.get_secret_value()
                    if resolved_settings.iishko_api_key is not None
                    else None
                ),
                base_url=resolved_settings.iishko_base_url,
                model=resolved_settings.iishko_model,
                timeout_seconds=resolved_settings.annotation_provider_timeout_seconds,
            )
        )
        resolved_annotator_registry.register(
            QwenLocalProvider(
                base_url=resolved_settings.qwen_local_base_url,
                model=resolved_settings.qwen_local_model,
                timeout_seconds=resolved_settings.annotation_provider_timeout_seconds,
            )
        )

    application = FastAPI(
        title="Local Translation Service",
        version="0.1.0",
        description="Local pluggable machine translation HTTP API.",
        docs_url=None,
    )
    application.state.settings = resolved_settings
    application.state.registry = resolved_registry
    application.state.translation_service = TranslationService(resolved_registry, resolved_settings)
    application.state.annotator_registry = resolved_annotator_registry
    application.state.annotation_service = annotation_service or AnnotationService(
        resolved_annotator_registry, resolved_settings
    )

    @application.middleware("http")
    async def add_request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, error: ApplicationError) -> JSONResponse:
        return _error_response(request, error)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = {
            "validation_errors": [
                {
                    "location": [str(part) for part in item["loc"]],
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors()
            ]
        }
        return _error_response(request, InvalidRequestError(details=details))

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        del error
        return _error_response(request, TranslationFailedError())

    @application.get("/docs", include_in_schema=False)
    async def scalar_api_reference() -> Response:
        return get_scalar_api_reference(
            openapi_url=application.openapi_url,
            title=f"{application.title} — API Reference",
            telemetry=False,
            agent=AgentScalarConfig(disabled=True),
        )

    application.include_router(translate_router)
    application.include_router(annotate_router)
    application.include_router(translators_router)
    application.include_router(health_router)
    return application


app = create_app()
