from typing import Annotated

from fastapi import APIRouter, Depends, Request

from translation_service.api.dependencies import get_translation_service
from translation_service.api.models import ERROR_RESPONSES, TranslateRequest, TranslateResponse
from translation_service.services.translation import TranslationService

router = APIRouter(prefix="/v1", tags=["translation"])


@router.post(
    "/translate",
    response_model=TranslateResponse,
    responses=ERROR_RESPONSES,
    summary="Translate text",
    operation_id="translateText",
)
async def translate_text(
    request: TranslateRequest,
    service: Annotated[TranslationService, Depends(get_translation_service)],
    http_request: Request,
) -> TranslateResponse:
    settings = http_request.app.state.settings
    http_request.state.operation = {
        "translator": (request.translator or settings.default_translator).strip().lower()[:64],
        "source_language": (request.source_language or settings.default_source_language)[:64],
        "target_language": request.target_language[:64],
        "text_length": len(request.text),
    }
    result = await service.translate(
        text=request.text,
        target_language=request.target_language,
        source_language=request.source_language,
        translator=request.translator,
        translator_params=request.translator_params,
    )
    return TranslateResponse.model_validate(result, from_attributes=True)
