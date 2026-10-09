import json
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from scalar_fastapi import AgentScalarConfig, get_scalar_api_reference
from starlette.middleware.base import RequestResponseEndpoint

from translation_service.api.errors import error_response
from translation_service.api.middleware import RequestBodyLimitMiddleware
from translation_service.api.models import ErrorEnvelope
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
from translation_service.core.workers import WorkerPool
from translation_service.providers.argos import ArgosProvider
from translation_service.providers.iishko import IishkoProvider
from translation_service.providers.marian import MarianProvider
from translation_service.providers.qwen_local import QwenLocalProvider
from translation_service.services.annotation import AnnotationService
from translation_service.services.annotator_registry import AnnotatorRegistry
from translation_service.services.registry import TranslatorRegistry
from translation_service.services.translation import TranslationService

logger = logging.getLogger("uvicorn.error.translation_service")


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
        responses={413: {"model": ErrorEnvelope}},
    )
    application.state.settings = resolved_settings
    workers = WorkerPool(resolved_settings.max_concurrent_operations)
    application.state.workers = workers
    application.state.registry = resolved_registry
    application.state.translation_service = TranslationService(
        resolved_registry, resolved_settings, workers=workers
    )
    application.state.annotator_registry = resolved_annotator_registry
    application.state.annotation_service = (
        annotation_service.with_workers(workers)
        if annotation_service is not None
        else AnnotationService(resolved_annotator_registry, resolved_settings, workers=workers)
    )

    application.add_middleware(
        RequestBodyLimitMiddleware, max_bytes=resolved_settings.max_request_body_bytes
    )

    @application.middleware("http")
    async def add_request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid4())
        started = perf_counter()
        status_code = 500
        try:
            try:
                response = await call_next(request)
            except Exception:
                response = error_response(request, TranslationFailedError())
            status_code = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        finally:
            route = request.scope.get("route")
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request.state.request_id,
                        "method": request.method,
                        "route": getattr(route, "path", "unmatched"),
                        "status_code": status_code,
                        "duration_ms": max(0, int((perf_counter() - started) * 1000)),
                        "result": getattr(
                            request.state,
                            "error_code",
                            "success" if status_code < 400 else "http_error",
                        ),
                        **getattr(request.state, "operation", {}),
                    }
                )
            )

    @application.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, error: ApplicationError) -> JSONResponse:
        return error_response(request, error)

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
        return error_response(request, InvalidRequestError(details=details))

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        del error
        return error_response(request, TranslationFailedError())

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
