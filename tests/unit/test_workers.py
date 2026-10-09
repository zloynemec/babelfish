from threading import Event

import anyio
import httpx
import pytest

from translation_service.core.config import Settings
from translation_service.core.workers import WorkerPool
from translation_service.domain.models import ProviderHealth
from translation_service.main import create_app
from translation_service.providers.fake import FakeTranslatorProvider
from translation_service.services.registry import TranslatorRegistry


async def wait_for_event(event: Event) -> None:
    with anyio.fail_after(2):
        while not event.is_set():
            await anyio.sleep(0.001)


@pytest.mark.anyio
async def test_abandoned_worker_keeps_slot_and_cancelled_waiter_never_runs() -> None:
    pool = WorkerPool(max_workers=1)
    started = Event()
    release = Event()
    finished = Event()
    waiter_started = Event()

    def blocked_work() -> str:
        started.set()
        try:
            assert release.wait(2), "Test did not release the worker"
            return "late"
        finally:
            finished.set()

    def waiting_work() -> str:
        waiter_started.set()
        return "unexpected"

    try:
        with pytest.raises(TimeoutError), anyio.fail_after(0.1):
            await pool.run(blocked_work)
        assert started.is_set()
        assert not finished.is_set()

        with pytest.raises(TimeoutError), anyio.fail_after(0.05):
            await pool.run(waiting_work)
        assert not waiter_started.is_set()
    finally:
        release.set()
        await wait_for_event(finished)

    with anyio.fail_after(2):
        assert await pool.run(lambda: "reused") == "reused"
    assert not waiter_started.is_set()


@pytest.mark.anyio
async def test_worker_exceptions_release_capacity() -> None:
    pool = WorkerPool(max_workers=1)

    def failing_work() -> None:
        raise ValueError("provider error")

    with pytest.raises(ValueError, match="provider error"):
        await pool.run(failing_work)

    with anyio.fail_after(2):
        assert await pool.run(lambda: 42) == 42


@pytest.mark.anyio
async def test_synchronous_health_work_does_not_block_event_loop() -> None:
    pool = WorkerPool(max_workers=1)
    started = Event()
    release = Event()
    finished = Event()

    def slow_health() -> None:
        started.set()
        try:
            assert release.wait(2), "Event loop could not release the worker"
        finally:
            finished.set()

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(pool.run, slow_health)
        try:
            await wait_for_event(started)
            await anyio.sleep(0)
            assert not finished.is_set()
        finally:
            release.set()


@pytest.mark.anyio
async def test_slow_translator_health_does_not_delay_http_liveness() -> None:
    started = Event()
    release = Event()
    finished = Event()

    class SlowHealthProvider(FakeTranslatorProvider):
        def health(self) -> ProviderHealth:
            started.set()
            try:
                release.wait(2)
                return super().health()
            finally:
                finished.set()

    registry = TranslatorRegistry()
    registry.register(SlowHealthProvider())
    app = create_app(settings=Settings(default_translator="fake"), registry=registry)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        async def list_translators() -> None:
            response = await client.get("/v1/translators")
            assert response.status_code == 200

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(list_translators)
            try:
                await wait_for_event(started)
                with anyio.fail_after(0.5):
                    response = await client.get("/health/live")
                assert response.status_code == 200
                assert not finished.is_set()
            finally:
                release.set()
