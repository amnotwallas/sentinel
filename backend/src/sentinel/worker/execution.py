"""Worker composition for the fenced execution application service."""

from __future__ import annotations

from opentelemetry.trace import Tracer
from sqlalchemy.orm import Session, sessionmaker

from sentinel.config import Settings
from sentinel.execution.domain import Lease
from sentinel.execution.orchestration import ExecutionOrchestrator
from sentinel.persistence.orchestration import PostgresOrchestrationStore
from sentinel.security.secrets import EnvironmentSecretResolver
from sentinel.telemetry.execution import OpenTelemetryTraceLifecycle
from sentinel.transport.http import HTTPTransportAdapter
from sentinel.worker.runtime import (
    Handler,
    HandlerCompletion,
    WorkerCancellation,
    joined_to_thread,
)


def build_execution_orchestrator(
    sessions: sessionmaker[Session], settings: Settings, tracer: Tracer
) -> ExecutionOrchestrator:
    """Compose approved adapters without placing HTTP policy in the worker loop."""
    return ExecutionOrchestrator(
        PostgresOrchestrationStore(sessions),
        HTTPTransportAdapter(ca_bundle=settings.target_ca_bundle),
        EnvironmentSecretResolver(),
        OpenTelemetryTraceLifecycle(tracer),
    )


def execution_handler(orchestrator: ExecutionOrchestrator) -> Handler:
    async def handle(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        await joined_to_thread(orchestrator.run, lease, cancellation)
        return HandlerCompletion.DURABLY_COMPLETED

    return handle
