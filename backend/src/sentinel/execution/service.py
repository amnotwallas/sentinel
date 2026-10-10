from uuid import UUID

from sentinel.execution.domain import ErrorCode, Lease, Probe
from sentinel.execution.ports import JobStore


class WorkService:
    def __init__(self, store: JobStore, lease_seconds: int = 60, max_deliveries: int = 3):
        self.store = store
        self.lease_seconds = lease_seconds
        self.max_deliveries = max_deliveries

    def enqueue_probe(self) -> Probe:
        return self.store.enqueue_probe(self.max_deliveries)

    def claim(self, owner: UUID) -> Lease | None:
        return self.store.claim(owner, self.lease_seconds)

    def heartbeat(self, lease: Lease) -> None:
        self.store.heartbeat(lease, self.lease_seconds)

    def start(self, lease: Lease) -> None:
        self.store.start(lease)

    def complete(self, lease: Lease) -> None:
        self.store.complete(lease)

    def fail(self, lease: Lease, code: ErrorCode, *, retryable: bool) -> None:
        self.store.fail(lease, code, retryable=retryable)
