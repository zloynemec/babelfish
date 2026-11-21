import anyio

from translation_service.services.annotation import AnnotationService

_PROBE_TEXT = (
    "The Moon orbits Earth about once every 27 days. "
    "We see different phases as sunlight illuminates the Moon from different angles."
)
_CACHE_SECONDS = 60
_TIMEOUT_SECONDS = 10


class IishkoHealthCheck:
    def __init__(self, annotation_service: AnnotationService) -> None:
        self._annotation_service = annotation_service
        self._lock = anyio.Lock()
        self._result: tuple[float, bool] | None = None

    async def is_healthy(self) -> bool:
        async with self._lock:
            result = self._result
            if result is not None and anyio.current_time() < result[0]:
                return result[1]

            try:
                with anyio.fail_after(_TIMEOUT_SECONDS):
                    await self._annotation_service.annotate(text=_PROBE_TEXT, annotator="iishko")
            except Exception:
                healthy = False
            else:
                healthy = True

            self._result = (anyio.current_time() + _CACHE_SECONDS, healthy)
            return healthy
