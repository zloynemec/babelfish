from collections.abc import Callable
from functools import partial

import anyio

from translation_service.core.workers import WorkerPool

_CACHE_SECONDS = 60
_TIMEOUT_SECONDS = 10


class IishkoHealthCheck:
    def __init__(self, probe: Callable[[float], bool] | None, workers: WorkerPool) -> None:
        self._probe = probe
        self._workers = workers
        self._lock = anyio.Lock()
        self._result: tuple[float, bool] | None = None

    async def is_healthy(self) -> bool:
        if self._probe is None:
            return False
        async with self._lock:
            result = self._result
            if result is not None and anyio.current_time() < result[0]:
                return result[1]

            try:
                with anyio.fail_after(_TIMEOUT_SECONDS):
                    healthy = await self._workers.run(partial(self._probe, _TIMEOUT_SECONDS))
            except TimeoutError:
                healthy = False

            self._result = (anyio.current_time() + _CACHE_SECONDS, healthy)
            return healthy
