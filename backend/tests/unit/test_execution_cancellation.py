from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from sentinel.execution.attempts import AttemptRecord
from sentinel.execution.domain import DispatchCertainty, Lease, TransportOutcome
from sentinel.execution.orchestration import ExecutionOrchestrator
from sentinel.execution.ports import DispatchCancelled, PinnedAttempt, TransportResult
from sentinel.security.secrets import EnvironmentSecretResolver, SecretNotFound
from sentinel.worker.runtime import WorkerCancellation
from tests.unit.test_execution_orchestration import (
    DEFINITION,
    ENVIRONMENT,
    EXECUTION_ID,
    LEASE,
    FakeStore,
    FakeTraceLifecycle,
    FakeTransport,
    attempt,
    ids,
)


def response() -> TransportResult:
    return TransportResult(
        TransportOutcome.RESPONSE_RECEIVED,
        DispatchCertainty.RESPONSE_RECEIVED,
        200,
        {},
        None,
        0,
        False,
    )


def test_cancellation_after_dispatch_checkpoint_prevents_network_io() -> None:
    cancellation = WorkerCancellation()

    class CancellingStore(FakeStore):
        def checkpoint_dispatch(
            self,
            attempt_id: UUID,
            lease: Lease,
            *,
            fingerprint: str,
            trace_id: str,
            span_id: str,
        ) -> AttemptRecord:
            result = super().checkpoint_dispatch(
                attempt_id,
                lease,
                fingerprint=fingerprint,
                trace_id=trace_id,
                span_id=span_id,
            )
            cancellation.cancel()
            return result

    store = CancellingStore(PinnedAttempt(EXECUTION_ID, attempt(), ENVIRONMENT, DEFINITION, False))
    transport = FakeTransport(store, response())
    orchestrator = ExecutionOrchestrator(
        store,
        transport,
        EnvironmentSecretResolver({}),
        FakeTraceLifecycle(),
        attempt_ids=ids,
    )

    with pytest.raises(DispatchCancelled):
        orchestrator.run(LEASE, cancellation)

    assert store.events == ["acquire", "checkpoint"]
    assert transport.requests == []
    assert store.work.attempt.dispatch_certainty == DispatchCertainty.POSSIBLY_SENT


def test_cancellation_after_transport_discards_stale_result() -> None:
    cancellation = WorkerCancellation()
    store = FakeStore(PinnedAttempt(EXECUTION_ID, attempt(), ENVIRONMENT, DEFINITION, False))

    class CancellingTransport(FakeTransport):
        def dispatch_cancellable(
            self, request: object, cancellation_signal: object
        ) -> TransportResult:
            cancellation.cancel()
            self.store.events.append("dispatch")
            return self.result

    transport = CancellingTransport(store, response())
    orchestrator = ExecutionOrchestrator(
        store,
        transport,
        EnvironmentSecretResolver({}),
        FakeTraceLifecycle(),
        attempt_ids=ids,
    )

    with pytest.raises(DispatchCancelled):
        orchestrator.run(LEASE, cancellation)

    assert store.events == ["acquire", "checkpoint", "dispatch"]
    assert store.work.attempt == replace(
        store.work.attempt,
        state=store.work.attempt.state,
    )
    assert not any(event.startswith("response:") for event in store.events)
    assert not any(event.startswith("transport_failed:") for event in store.events)


def test_cancellation_during_preparation_prevents_failure_checkpoint() -> None:
    cancellation = WorkerCancellation()
    environment = {
        **ENVIRONMENT,
        "secret_references": [{"$secret": "TOKEN"}],
    }
    definition = {
        **DEFINITION,
        "request": {
            "method": "GET",
            "path": "/health",
            "headers": [{"name": "Authorization", "value": {"$secret": "TOKEN"}}],
        },
    }

    class CancellingResolver:
        def resolve(self, name: str) -> str:
            cancellation.cancel()
            raise SecretNotFound(name)

    store = FakeStore(PinnedAttempt(EXECUTION_ID, attempt(), environment, definition, False))
    orchestrator = ExecutionOrchestrator(
        store,
        FakeTransport(store, response()),
        CancellingResolver(),
        FakeTraceLifecycle(),
        attempt_ids=ids,
    )

    with pytest.raises(DispatchCancelled):
        orchestrator.run(LEASE, cancellation)

    assert store.events == ["acquire"]
