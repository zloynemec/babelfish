from typing import Annotated

from fastapi import APIRouter, Depends

from translation_service.api.dependencies import get_registry, get_settings
from translation_service.api.models import ERROR_RESPONSES, LiveResponse, ReadyResponse
from translation_service.core.config import Settings
from translation_service.core.errors import TranslatorUnavailableError
from translation_service.services.registry import TranslatorRegistry

router = APIRouter(tags=["health"])


@router.get(
    "/health/live",
    response_model=LiveResponse,
    summary="Liveness probe",
    operation_id="healthLive",
)
async def health_live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    responses={503: ERROR_RESPONSES[503]},
    summary="Readiness probe",
    operation_id="healthReady",
)
async def health_ready(
    registry: Annotated[TranslatorRegistry, Depends(get_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadyResponse:
    try:
        provider = registry.get(settings.default_translator)
        ready = provider.health().ready
    except Exception:
        ready = False

    if not ready:
        raise TranslatorUnavailableError(
            "Default translator is not ready",
            details={"translator": settings.default_translator},
        )

    return ReadyResponse(status="ready", default_translator=settings.default_translator)
