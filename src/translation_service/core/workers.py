from collections.abc import Callable
from threading import Lock
from typing import cast

import anyio


class WorkerPool:
    """Keep capacity reserved until synchronous work physically finishes."""

    def __init__(self, max_workers: int) -> None:
        self._slots = anyio.Semaphore(max_workers, max_value=max_workers)

    async def run[T](self, function: Callable[[], T]) -> T:
        await self._slots.acquire()
        lock = Lock()
        started = False
        cancelled = False

        def invoke() -> T | None:
            nonlocal started
            with lock:
                if cancelled:
                    return None
                started = True
            try:
                return function()
            finally:
                anyio.from_thread.run_sync(self._slots.release)

        try:
            return cast(T, await anyio.to_thread.run_sync(invoke, abandon_on_cancel=True))
        finally:
            # Cancellation can happen after dispatch but before the thread starts.
            with lock:
                if not started:
                    cancelled = True
                    self._slots.release()
