from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Response

from translation_service.api.dependencies import (
    get_iishko_health,
    get_registry,
    get_settings,
    get_workers,
)
from translation_service.api.models import HealthChecks, HealthResponse, TranslatorHealth
from translation_service.core.config import Settings
from translation_service.core.workers import WorkerPool
from translation_service.services.iishko_health import IishkoHealthCheck
from translation_service.services.registry import TranslatorRegistry

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Default translator is unavailable"}},
    summary="Check service health",
    description=(
        "Reports liveness, default translator readiness, and a cached Iishko annotation probe. "
        "If only Iishko fails, the status is degraded and the HTTP response is 200. "
        "If the default translator fails, the HTTP response is 503 with all check results."
    ),
    operation_id="health",
)
async def health(
    response: Response,
    registry: Annotated[TranslatorRegistry, Depends(get_registry)],
    settings: Annotated[Settings, Depends(get_settings)],
    workers: Annotated[WorkerPool, Depends(get_workers)],
    iishko: Annotated[IishkoHealthCheck, Depends(get_iishko_health)],
) -> HealthResponse:
    translator_ready = False
    iishko_ready = False

    async def check_translator() -> None:
        nonlocal translator_ready
        try:
            provider = registry.get(settings.default_translator)
            with anyio.fail_after(settings.translation_timeout_seconds):
                translator_ready = (await workers.run(provider.health)).ready
        except Exception:
            translator_ready = False

    async def check_iishko() -> None:
        nonlocal iishko_ready
        iishko_ready = await iishko.is_healthy()

    async with anyio.create_task_group() as group:
        group.start_soon(check_translator)
        group.start_soon(check_iishko)

    if not translator_ready:
        response.status_code = 503
    return HealthResponse(
        status=("ok" if iishko_ready else "degraded") if translator_ready else "not_ready",
        checks=HealthChecks(
            live=True,
            translator=TranslatorHealth(name=settings.default_translator, ready=translator_ready),
            iishko=iishko_ready,
        ),
    )
