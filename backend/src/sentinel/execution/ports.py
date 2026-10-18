from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sentinel.execution.attempts import AttemptRecord, ResponseArtifact
from sentinel.execution.domain import (
    DispatchCertainty,
    ErrorCode,
    Lease,
    PreparationErrorCode,
    Probe,
    RedirectRejectionCode,
    TransportOutcome,
)
from sentinel.execution.preparation import PreparedRequest

IdFactory = Callable[[], UUID]


class DispatchCancelled(RuntimeError):
    """Lease ownership or process liveness is no longer confirmed."""

    def __init__(self) -> None:
        super().__init__("dispatch_cancelled")


class CancellationSignal(Protocol):
    """Thread-safe cooperative cancellation checked at side-effect boundaries."""

    def is_cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


class NoCancellation:
    def is_cancelled(self) -> bool:
        return False

    def raise_if_cancelled(self) -> None:
        pass


NO_CANCELLATION = NoCancellation()


@dataclass(frozen=True, slots=True)
class TransportResult:
    """Bounded, redacted adapter output safe to pass to a fenced checkpoint."""

    outcome: TransportOutcome
    certainty: DispatchCertainty
    status_code: int | None
    headers: Mapping[str, str]
    body: bytes | None
    source_bytes_captured: int
    truncated: bool
    redirect_rejection_code: RedirectRejectionCode | None = None
    redaction_unavailable: bool = False
    not_sent_proof: str | None = None
    body_kind: str | None = None
    body_content: object | None = None


@dataclass(frozen=True, slots=True)
class PinnedAttempt:
    """Exact immutable catalog inputs selected for one materialized execution item."""

    execution_id: UUID
    attempt: AttemptRecord
    environment_document: object
    test_definition: object
    unsafe_replay_acknowledged: bool


class TransportAdapter(Protocol):
    """M3-03's network boundary; M3-02 provides only this contract."""

    def dispatch(self, request: PreparedRequest) -> TransportResult: ...


class CancellableTransportAdapter(Protocol):
    """M3-04 transport seam for cooperative lease-loss cancellation."""

    def dispatch_cancellable(
        self,
        request: PreparedRequest,
        cancellation: CancellationSignal,
    ) -> TransportResult: ...


class DispatchTrace(Protocol):
    """Execution-facing trace handle without an OpenTelemetry dependency."""

    @property
    def trace_id(self) -> str: ...

    @property
    def span_id(self) -> str: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def end(
        self,
        *,
        status_code: int | None,
        outcome: TransportOutcome | None,
        certainty: DispatchCertainty | None,
    ) -> None: ...


class TraceLifecycle(Protocol):
    def start(
        self,
        *,
        execution_id: UUID,
        attempt_id: UUID,
        method: str,
        headers: Mapping[str, str],
    ) -> DispatchTrace: ...


class JobStore(Protocol):
    def enqueue_probe(self, max_deliveries: int) -> Probe: ...
    def claim(self, owner: UUID, lease_seconds: int) -> Lease | None: ...
    def heartbeat(self, lease: Lease, lease_seconds: int) -> None: ...
    def start(self, lease: Lease) -> None: ...
    def complete(self, lease: Lease) -> None: ...
    def fail(self, lease: Lease, code: ErrorCode, *, retryable: bool) -> None: ...


class AttemptStore(Protocol):
    """Persistence port used by M3-03/M3-04; implementations must fence writes."""

    def create_prepared(self, execution_item_id: UUID, *, attempt_id: UUID) -> AttemptRecord: ...

    def checkpoint_dispatch(
        self,
        attempt_id: UUID,
        lease: Lease,
        *,
        fingerprint: str,
        trace_id: str,
        span_id: str,
    ) -> AttemptRecord: ...

    def fail_preparation(
        self, attempt_id: UUID, lease: Lease, code: PreparationErrorCode
    ) -> AttemptRecord: ...

    def record_response(
        self,
        attempt_id: UUID,
        lease: Lease,
        artifact: ResponseArtifact,
        *,
        outcome: TransportOutcome,
    ) -> AttemptRecord: ...

    def record_transport_failure(
        self,
        attempt_id: UUID,
        lease: Lease,
        *,
        outcome: TransportOutcome,
        certainty: DispatchCertainty,
        not_sent_proof: str | None = None,
        redirect_code: RedirectRejectionCode | None = None,
        artifact: ResponseArtifact | None = None,
    ) -> AttemptRecord: ...


class OrchestrationStore(Protocol):
    """Short, fenced persistence operations used by execution orchestration."""

    def acquire_next(self, lease: Lease, *, attempt_id: UUID) -> PinnedAttempt | None: ...

    def checkpoint_dispatch(
        self,
        attempt_id: UUID,
        lease: Lease,
        *,
        fingerprint: str,
        trace_id: str,
        span_id: str,
    ) -> AttemptRecord: ...

    def fail_preparation(
        self, attempt_id: UUID, lease: Lease, code: PreparationErrorCode
    ) -> bool: ...

    def record_response(
        self,
        attempt_id: UUID,
        lease: Lease,
        artifact: ResponseArtifact,
        *,
        outcome: TransportOutcome,
    ) -> bool: ...

    def record_transport_failure(
        self,
        attempt_id: UUID,
        lease: Lease,
        *,
        outcome: TransportOutcome,
        certainty: DispatchCertainty,
        not_sent_proof: str | None = None,
        redirect_code: RedirectRejectionCode | None = None,
        artifact: ResponseArtifact | None = None,
    ) -> bool: ...

    def schedule_replay(
        self, attempt_id: UUID, lease: Lease, *, successor_id: UUID
    ) -> AttemptRecord: ...

    def mark_indeterminate(self, attempt_id: UUID, lease: Lease) -> None: ...

    def resume_terminal(self, attempt_id: UUID, lease: Lease) -> bool: ...

    def complete_execution(self, lease: Lease) -> None: ...
