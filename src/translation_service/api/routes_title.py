from typing import Annotated

from fastapi import APIRouter, Depends, Request

from translation_service.api.dependencies import get_title_service
from translation_service.api.models import TITLE_ERROR_RESPONSES, TitleRequest, TitleResponse
from translation_service.services.title import TitleService

router = APIRouter(prefix="/v1", tags=["title"])


@router.post(
    "/title",
    response_model=TitleResponse,
    responses=TITLE_ERROR_RESPONSES,
    summary="Generate a title",
    operation_id="generateTitle",
)
async def generate_title(
    request: TitleRequest,
    service: Annotated[TitleService, Depends(get_title_service)],
    http_request: Request,
) -> TitleResponse:
    operation = http_request.state.operation
    operation.update(
        {
            "annotator": (request.annotator or http_request.app.state.settings.default_annotator)
            .strip()
            .lower()[:64],
            "target_language": request.target_language[:64],
            "text_length": len(request.text),
        }
    )
    result = await service.generate(
        text=request.text,
        target_language=request.target_language,
        annotator=request.annotator,
        annotator_params=request.annotator_params,
        operation=operation,
    )
    return TitleResponse.model_validate(result)
