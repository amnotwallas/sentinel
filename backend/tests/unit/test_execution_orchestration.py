from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from sentinel.execution.attempts import AttemptRecord, ResponseArtifact
from sentinel.execution.domain import AttemptState, DispatchCertainty, Lease, TransportOutcome
from sentinel.execution.orchestration import ExecutionOrchestrator, replay_allowed
from sentinel.execution.ports import (
    CancellationSignal,
    DispatchTrace,
    OrchestrationStore,
    PinnedAttempt,
    TraceLifecycle,
    TransportResult,
)
from sentinel.execution.preparation import PreparedRequest
from sentinel.security.secrets import EnvironmentSecretResolver

NOW = datetime(2030, 1, 1, tzinfo=UTC)
EXECUTION_ID = UUID("10000000-0000-4000-8000-000000000001")
ITEM_ID = UUID("10000000-0000-4000-8000-000000000002")
ATTEMPT_ID = UUID("10000000-0000-4000-8000-000000000003")
JOB_ID = UUID("10000000-0000-4000-8000-000000000004")
OWNER_ID = UUID("10000000-0000-4000-8000-000000000005")
TOKEN_ID = UUID("10000000-0000-4000-8000-000000000006")
LEASE = Lease(JOB_ID, EXECUTION_ID, "execute_execution", OWNER_ID, TOKEN_ID, NOW, 1)

ENVIRONMENT = {
    "schema_version": 1,
    "base_url": "https://api.example.test/",
    "variables": {},
    "secret_references": [],
    "target_policy": {},
}
DEFINITION = {
    "schema_version": 1,
    "request": {"method": "GET", "path": "/health"},
}


def attempt(state: AttemptState = AttemptState.PREPARED) -> AttemptRecord:
    dispatched = state != AttemptState.PREPARED
    return AttemptRecord(
        ATTEMPT_ID,
        ITEM_ID,
        1,
        state,
        DispatchCertainty.POSSIBLY_SENT if dispatched else DispatchCertainty.NOT_STARTED,
        "a" * 64 if dispatched else None,
        NOW,
        NOW if dispatched else None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "b" * 32 if dispatched else None,
        "c" * 16 if dispatched else None,
        True,
    )


class FakeStore(OrchestrationStore):
    def __init__(self, work: PinnedAttempt) -> None:
        self.work = work
        self.events: list[str] = []
        self.done = False

    def acquire_next(self, lease: Lease, *, attempt_id: UUID) -> PinnedAttempt | None:
        self.events.append("acquire")
        return None if self.done else self.work

    def checkpoint_dispatch(
        self,
        attempt_id: UUID,
        lease: Lease,
        *,
        fingerprint: str,
        trace_id: str,
        span_id: str,
    ) -> AttemptRecord:
        self.events.append("checkpoint")
        self.work = replace(
            self.work,
            attempt=replace(
                self.work.attempt,
                state=AttemptState.DISPATCHING,
                dispatch_certainty=DispatchCertainty.POSSIBLY_SENT,
                request_fingerprint=fingerprint,
                primary_trace_id=trace_id,
                client_span_id=span_id,
                dispatch_recorded_at=NOW,
            ),
        )
        return self.work.attempt

    def fail_preparation(self, attempt_id: UUID, lease: Lease, code: object) -> bool:
        self.events.append(f"prepare_failed:{code}")
        self.done = True
        return True

    def record_response(
        self,
        attempt_id: UUID,
        lease: Lease,
        artifact: ResponseArtifact,
        *,
        outcome: TransportOutcome,
    ) -> bool:
        self.events.append(f"response:{artifact.body_kind}:{artifact.body_content}")
        self.done = True
        return True

    def record_transport_failure(self, *args: object, **kwargs: object) -> bool:
        self.events.append(f"transport_failed:{kwargs.get('artifact') is not None}")
        self.done = True
        return True

    def schedule_replay(
        self, attempt_id: UUID, lease: Lease, *, successor_id: UUID
    ) -> AttemptRecord:
        self.events.append("replay")
        self.done = True
        return attempt()

    def mark_indeterminate(self, attempt_id: UUID, lease: Lease) -> None:
        self.events.append("indeterminate")
        self.done = True

    def resume_terminal(self, attempt_id: UUID, lease: Lease) -> bool:
        self.events.append("resume_terminal")
        self.done = True
        return True

    def complete_execution(self, lease: Lease) -> None:
        self.events.append("complete")
        self.done = True


class FakeTransport:
    def __init__(self, store: FakeStore, result: TransportResult) -> None:
        self.store = store
        self.result = result
        self.requests: list[PreparedRequest] = []

    def dispatch(self, request: PreparedRequest) -> TransportResult:
        assert self.store.events[-1] == "checkpoint"
        self.store.events.append("dispatch")
        self.requests.append(request)
        return self.result

    def dispatch_cancellable(
        self, request: PreparedRequest, cancellation: CancellationSignal
    ) -> TransportResult:
        cancellation.raise_if_cancelled()
        return self.dispatch(request)


class FakeDispatchTrace(DispatchTrace):
    def __init__(self, headers: dict[str, str], sequence: int) -> None:
        self._trace_id = f"{sequence:032x}"
        self._span_id = f"{sequence:016x}"
        self._headers = {
            **headers,
            "traceparent": f"00-{self._trace_id}-{self._span_id}-01",
            "baggage": "vendor=value,sentinel.execution.id=fake,sentinel.attempt.id=fake",
        }
        self.ends: list[tuple[int | None, TransportOutcome | None, DispatchCertainty | None]] = []

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def span_id(self) -> str:
        return self._span_id

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    def end(
        self,
        *,
        status_code: int | None,
        outcome: TransportOutcome | None,
        certainty: DispatchCertainty | None,
    ) -> None:
        self.ends.append((status_code, outcome, certainty))


class FakeTraceLifecycle(TraceLifecycle):
    def __init__(self) -> None:
        self.started: list[FakeDispatchTrace] = []

    def start(
        self,
        *,
        execution_id: UUID,
        attempt_id: UUID,
        method: str,
        headers: Mapping[str, str],
    ) -> FakeDispatchTrace:
        active = FakeDispatchTrace(dict(headers), len(self.started) + 1)
        self.started.append(active)
        return active


def ids() -> UUID:
    return UUID("20000000-0000-4000-8000-000000000001")


def test_response_is_dispatched_only_after_checkpoint_and_preserves_body_shape() -> None:
    store = FakeStore(PinnedAttempt(EXECUTION_ID, attempt(), ENVIRONMENT, DEFINITION, False))
    transport = FakeTransport(
        store,
        TransportResult(
            TransportOutcome.RESPONSE_RECEIVED,
            DispatchCertainty.RESPONSE_RECEIVED,
            200,
            {"content-type": "application/json"},
            b'{"ok":true}',
            11,
            False,
            body_kind="json",
            body_content={"ok": True},
        ),
    )
    traces = FakeTraceLifecycle()
    service = ExecutionOrchestrator(
        store,
        transport,
        EnvironmentSecretResolver({}),
        traces,
        attempt_ids=ids,
        clock=lambda: NOW,
    )

    service.run(LEASE)

    assert store.events == ["acquire", "checkpoint", "dispatch", "response:json:{'ok': True}"]
    assert transport.requests[0].headers["traceparent"] == f"00-{'0' * 31}1-{'0' * 15}1-01"
    assert store.work.attempt.primary_trace_id == traces.started[0].trace_id
    assert store.work.attempt.client_span_id == traces.started[0].span_id
    assert traces.started[0].ends == [
        (200, TransportOutcome.RESPONSE_RECEIVED, DispatchCertainty.RESPONSE_RECEIVED)
    ]


def test_dispatching_unsafe_attempt_without_consent_becomes_indeterminate() -> None:
    definition = {**DEFINITION, "request": {"method": "POST", "path": "/charge"}}
    store = FakeStore(
        PinnedAttempt(
            EXECUTION_ID, attempt(AttemptState.DISPATCHING), ENVIRONMENT, definition, False
        )
    )
    transport = FakeTransport(
        store,
        TransportResult(
            TransportOutcome.RESPONSE_RECEIVED,
            DispatchCertainty.RESPONSE_RECEIVED,
            200,
            {},
            None,
            0,
            False,
        ),
    )

    ExecutionOrchestrator(
        store, transport, EnvironmentSecretResolver({}), FakeTraceLifecycle()
    ).run(LEASE)

    assert store.events == ["acquire", "indeterminate"]
    assert transport.requests == []


def test_terminal_observation_resumes_without_dispatch() -> None:
    store = FakeStore(
        PinnedAttempt(
            EXECUTION_ID,
            attempt(AttemptState.TRANSPORT_FAILED),
            ENVIRONMENT,
            DEFINITION,
            False,
        )
    )
    transport = FakeTransport(
        store,
        TransportResult(
            TransportOutcome.RESPONSE_RECEIVED,
            DispatchCertainty.RESPONSE_RECEIVED,
            200,
            {},
            None,
            0,
            False,
        ),
    )

    ExecutionOrchestrator(
        store, transport, EnvironmentSecretResolver({}), FakeTraceLifecycle()
    ).run(LEASE)

    assert store.events == ["acquire", "resume_terminal"]
    assert transport.requests == []


def test_replay_policy_is_intentionally_narrow() -> None:
    assert all(replay_allowed(method, False) for method in ("GET", "HEAD", "OPTIONS"))
    assert not replay_allowed("PUT", False)
    assert replay_allowed("POST", True)


def test_later_prewrite_redirect_failure_does_not_create_forbidden_artifact() -> None:
    store = FakeStore(PinnedAttempt(EXECUTION_ID, attempt(), ENVIRONMENT, DEFINITION, False))
    transport = FakeTransport(
        store,
        TransportResult(
            TransportOutcome.DNS_FAILURE,
            DispatchCertainty.RESPONSE_RECEIVED,
            302,
            {"location": "[REDACTED]"},
            b"redirect",
            8,
            False,
            body_kind="text",
            body_content="redirect",
        ),
    )

    ExecutionOrchestrator(
        store,
        transport,
        EnvironmentSecretResolver({}),
        FakeTraceLifecycle(),
        attempt_ids=ids,
        clock=lambda: NOW,
    ).run(LEASE)

    assert store.events[-1] == "transport_failed:False"


@pytest.mark.parametrize("failure_point", ["checkpoint", "transport"])
def test_active_span_ends_when_checkpoint_or_transport_raises(failure_point: str) -> None:
    class FailingStore(FakeStore):
        def checkpoint_dispatch(
            self,
            attempt_id: UUID,
            lease: Lease,
            *,
            fingerprint: str,
            trace_id: str,
            span_id: str,
        ) -> AttemptRecord:
            if failure_point == "checkpoint":
                raise RuntimeError("checkpoint_failed")
            return super().checkpoint_dispatch(
                attempt_id,
                lease,
                fingerprint=fingerprint,
                trace_id=trace_id,
                span_id=span_id,
            )

    class FailingTransport(FakeTransport):
        def dispatch(self, request: PreparedRequest) -> TransportResult:
            if failure_point == "transport":
                raise RuntimeError("transport_failed")
            return super().dispatch(request)

    store = FailingStore(PinnedAttempt(EXECUTION_ID, attempt(), ENVIRONMENT, DEFINITION, False))
    transport = FailingTransport(store, response_result())
    traces = FakeTraceLifecycle()

    with pytest.raises(RuntimeError, match=f"{failure_point}_failed"):
        ExecutionOrchestrator(
            store,
            transport,
            EnvironmentSecretResolver({}),
            traces,
            attempt_ids=ids,
        ).run(LEASE)

    assert traces.started[0].ends == [(None, None, None)]


def response_result() -> TransportResult:
    return TransportResult(
        TransportOutcome.RESPONSE_RECEIVED,
        DispatchCertainty.RESPONSE_RECEIVED,
        200,
        {},
        None,
        0,
        False,
    )
