from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from translation_service.api.models import ErrorBody, ErrorEnvelope
from translation_service.core.errors import ApplicationError


def error_response(request: Request, error: ApplicationError) -> JSONResponse:
    request.state.error_code = error.code
    body = ErrorEnvelope(
        error=ErrorBody(
            code=error.code,
            message=error.message,
            details=error.details,
            request_id=getattr(request.state, "request_id", str(uuid4())),
        )
    )
    return JSONResponse(status_code=error.status_code, content=body.model_dump(mode="json"))
