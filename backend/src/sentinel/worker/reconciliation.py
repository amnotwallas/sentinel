"""Worker handler for read-only trace reconciliation."""

from sentinel.execution.domain import Lease
from sentinel.telemetry.reconciliation import TraceReconciliationService
from sentinel.worker.runtime import Handler, HandlerCompletion, WorkerCancellation


def reconciliation_handler(service: TraceReconciliationService) -> Handler:
    async def handle(lease: Lease, cancellation: WorkerCancellation) -> HandlerCompletion:
        await service.reconcile(lease, cancellation)
        return HandlerCompletion.DURABLY_COMPLETED

    return handle
