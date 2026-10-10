import asyncio
import logging
import random
import signal
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from sentinel.config import Settings
from sentinel.execution.domain import InfrastructureFailure
from sentinel.execution.service import WorkService
from sentinel.persistence.database import create_database
from sentinel.persistence.queue import PostgresJobStore
from sentinel.telemetry.runtime import event, provider
from sentinel.worker.runtime import Worker

HEALTH_FILE = Path("/tmp/sentinel-worker-health")


async def run(settings: Settings) -> None:
    engine, sessions = create_database(settings.database_url.get_secret_value())
    tracing = provider("sentinel-worker", settings.otlp_endpoint)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    active: asyncio.Task[bool] | None = None

    def shutdown() -> None:
        stop.set()
        if active is not None:
            active.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    async def healthy() -> None:
        await asyncio.to_thread(HEALTH_FILE.touch)

    worker = Worker(
        WorkService(PostgresJobStore(sessions), settings.lease_seconds, settings.max_deliveries),
        uuid4(),
        heartbeat_seconds=settings.heartbeat_seconds,
        health=healthy,
        tracer=tracing.get_tracer(__name__),
    )
    event("worker_started")
    await asyncio.to_thread(HEALTH_FILE.unlink, missing_ok=True)
    try:
        while not stop.is_set():
            try:
                active = asyncio.create_task(worker.run_once())
                worked = await active
                await healthy()
            except InfrastructureFailure:
                event("worker_database_unavailable")
                worked = False
            except asyncio.CancelledError:
                if stop.is_set():
                    break
                raise
            finally:
                active = None
            if not worked:
                with_timeout = settings.poll_seconds * random.uniform(0.8, 1.0)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=with_timeout)
                except TimeoutError:
                    pass
    finally:
        await asyncio.to_thread(HEALTH_FILE.unlink, missing_ok=True)
        await asyncio.to_thread(engine.dispose)
        await asyncio.to_thread(tracing.shutdown)
        event("worker_stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        settings = Settings()
    except ValidationError:
        raise SystemExit("invalid_configuration") from None
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
