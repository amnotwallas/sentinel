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
from sentinel.telemetry.reconciliation import TraceReconciliationService
from sentinel.telemetry.runtime import event, provider
from sentinel.telemetry.tempo import TempoLookupAdapter
from sentinel.worker.execution import build_execution_orchestrator, execution_handler
from sentinel.worker.reconciliation import reconciliation_handler
from sentinel.worker.runtime import Worker, joined_to_thread, probe_handler

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
        await joined_to_thread(HEALTH_FILE.touch)

    worker_tracer = tracing.get_tracer(__name__)
    orchestrator = build_execution_orchestrator(sessions, settings, worker_tracer)
    jobs = PostgresJobStore(sessions)
    tempo = TempoLookupAdapter(settings.tempo_url)
    worker = Worker(
        WorkService(jobs, settings.lease_seconds, settings.max_deliveries),
        uuid4(),
        heartbeat_seconds=settings.heartbeat_seconds,
        handlers={
            "probe": probe_handler,
            "execute_execution": execution_handler(orchestrator),
            "correlate_trace": reconciliation_handler(
                TraceReconciliationService(
                    jobs, tempo, linked_search_enabled=settings.linked_trace_search_enabled
                )
            ),
        },
        health=healthy,
        tracer=worker_tracer,
    )
    event("worker_started")
    await joined_to_thread(HEALTH_FILE.unlink, missing_ok=True)
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
        await joined_to_thread(HEALTH_FILE.unlink, missing_ok=True)
        await joined_to_thread(engine.dispose)
        await joined_to_thread(tempo.close)
        await joined_to_thread(tracing.shutdown)
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
