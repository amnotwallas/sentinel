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


@dataclass(frozen=True, slots=True)
class TransportResult:
    """Bounded adapter output; persistence still redacts before storage."""

    outcome: TransportOutcome
    certainty: DispatchCertainty
    status_code: int | None
    headers: Mapping[str, str]
    body: bytes | None
    source_bytes_captured: int
    truncated: bool


class TransportAdapter(Protocol):
    """M3-03's network boundary; M3-02 provides only this contract."""

    def dispatch(self, request: PreparedRequest) -> TransportResult: ...


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
        self, attempt_id: UUID, lease: Lease, artifact: ResponseArtifact
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
