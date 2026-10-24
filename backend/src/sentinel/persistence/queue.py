from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.domain import (
    ErrorCode,
    InfrastructureFailure,
    JobState,
    Lease,
    LeaseLost,
    Probe,
    validate_transition,
)
from sentinel.execution.ports import IdFactory
from sentinel.persistence.models import (
    ExecutionItemRow,
    ExecutionRow,
    JobRow,
    TestAttemptRow,
    TraceReferenceRow,
)
from sentinel.persistence.trace_references import validate_evidence
from sentinel.telemetry.ports import TraceLookup, TraceLookupStatus


@dataclass(frozen=True, slots=True)
class CorrelationSnapshot:
    trace_id: str
    expected_span_id: str
    deadline_at: datetime
    first_checked_at: datetime | None
    lookup_attempt_count: int
    status: str


@dataclass(frozen=True, slots=True)
class CorrelationUpdate:
    terminal: bool
    status: str
    lookup_attempt_count: int


class PostgresJobStore:
    """One session/short transaction per operation, never held across handler I/O."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
        ids: IdFactory = uuid4,
    ) -> None:
        self.sessions = sessions
        self.clock = clock
        self.ids = ids

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        try:
            with self.sessions.begin() as session:
                yield session
        except OperationalError:
            raise InfrastructureFailure("database_operation_failed") from None

    def _now(self, session: Session) -> datetime:
        if self.clock:
            return self.clock()
        value = session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("PostgreSQL clock unavailable")
        return value

    def enqueue_probe(self, max_deliveries: int) -> Probe:
        if not 1 <= max_deliveries <= 3:
            raise ValueError("max_deliveries must be between 1 and 3")
        with self._transaction() as session:
            now = self._now(session)
            execution_id, job_id = self.ids(), self.ids()
            session.add(ExecutionRow(id=execution_id, status="queued", created_at=now))
            session.flush()
            session.add(
                JobRow(
                    id=job_id,
                    kind="probe",
                    subject_id=execution_id,
                    state="pending",
                    available_at=now,
                    delivery_count=0,
                    max_deliveries=max_deliveries,
                    created_at=now,
                )
            )
        return Probe(execution_id, job_id)

    def claim(self, owner: UUID, lease_seconds: int) -> Lease | None:
        # Bound cleanup work so a backlog of exhausted jobs cannot monopolize one claim.
        with self._transaction() as session:
            for _ in range(100):
                now = self._now(session)
                row = session.scalar(
                    select(JobRow)
                    .where(
                        or_(
                            and_(JobRow.state == "pending", JobRow.available_at <= now),
                            and_(JobRow.state == "leased", JobRow.lease_expires_at <= now),
                        )
                    )
                    # Preserve execution recovery priority while correlation work is additive.
                    .order_by(
                        case((JobRow.kind == "correlate_trace", 1), else_=0),
                        JobRow.available_at,
                        JobRow.created_at,
                        JobRow.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if row is None:
                    return None
                now = self._now(session)
                if row.delivery_count >= row.max_deliveries:
                    self._dead(session, row, ErrorCode.DELIVERY_EXHAUSTED, now)
                    session.flush()
                    continue
                validate_transition(
                    JobState(row.state), JobState.LEASED, renewal=row.state == "leased"
                )
                row.state = JobState.LEASED
                row.lease_owner = owner
                row.lease_token = self.ids()
                row.lease_expires_at = now + timedelta(seconds=lease_seconds)
                row.delivery_count += 1
                lease = Lease(
                    row.id,
                    row.subject_id,
                    row.kind,
                    owner,
                    row.lease_token,
                    row.lease_expires_at,
                    row.delivery_count,
                    row.trace_reference_id,
                )
                return lease
        return None

    def _owned(self, session: Session, lease: Lease) -> tuple[JobRow, datetime]:
        row = session.scalar(
            select(JobRow)
            .where(
                JobRow.id == lease.job_id,
                JobRow.state == "leased",
                JobRow.lease_owner == lease.owner,
                JobRow.lease_token == lease.token,
            )
            .with_for_update()
        )
        # Read DB time after any lock wait; an expired token cannot be revived.
        now = self._now(session)
        if row is None or row.lease_expires_at is None or row.lease_expires_at <= now:
            raise LeaseLost("lease no longer owned")
        return row, now

    def heartbeat(self, lease: Lease, lease_seconds: int) -> None:
        with self._transaction() as session:
            row, now = self._owned(session, lease)
            validate_transition(JobState(row.state), JobState.LEASED, renewal=True)
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)

    def start(self, lease: Lease) -> None:
        with self._transaction() as session:
            row, now = self._owned(session, lease)
            if row.kind == "correlate_trace":
                self._validate_correlation(session, row)
                return
            execution = self._subject(session, row)
            if execution.status == "queued":
                execution.status = "running"
                execution.started_at = now
            elif execution.status != "running":
                raise LeaseLost("subject is terminal")

    def complete(self, lease: Lease) -> None:
        with self._transaction() as session:
            row, now = self._owned(session, lease)
            if row.kind == "correlate_trace":
                self._validate_correlation(session, row)
                validate_transition(JobState(row.state), JobState.SUCCEEDED)
                row.state = JobState.SUCCEEDED
                row.finished_at = now
                self._clear_lease(row)
                return
            execution = self._subject(session, row)
            if execution.status != "running":
                raise ValueError("only a running execution can complete")
            validate_transition(JobState(row.state), JobState.SUCCEEDED)
            execution.status = "completed"
            execution.finished_at = now
            row.state = JobState.SUCCEEDED
            row.finished_at = now
            self._clear_lease(row)

    def fail(self, lease: Lease, code: ErrorCode, *, retryable: bool) -> None:
        with self._transaction() as session:
            row, now = self._owned(session, lease)
            if not retryable or row.delivery_count >= row.max_deliveries:
                self._dead(session, row, code, now)
            else:
                validate_transition(JobState(row.state), JobState.PENDING)
                row.state = JobState.PENDING
                row.available_at = now + timedelta(seconds=5 if row.delivery_count == 1 else 30)
                row.last_error_code = code
                self._clear_lease(row)

    @staticmethod
    def _subject(session: Session, row: JobRow) -> ExecutionRow:
        execution = session.scalar(
            select(ExecutionRow).where(ExecutionRow.id == row.subject_id).with_for_update()
        )
        if execution is None:
            raise RuntimeError("missing execution subject")
        return execution

    @staticmethod
    def _validate_correlation(session: Session, row: JobRow) -> TraceReferenceRow:
        if row.trace_reference_id is None:
            raise LeaseLost("correlation job has no trace reference")
        reference = session.scalar(
            select(TraceReferenceRow)
            .where(
                TraceReferenceRow.id == row.trace_reference_id,
                TraceReferenceRow.execution_id == row.subject_id,
                TraceReferenceRow.relation == "primary",
            )
            .with_for_update()
        )
        if reference is None:
            raise LeaseLost("correlation reference is invalid")
        return reference

    def correlation_snapshot(self, lease: Lease) -> CorrelationSnapshot:
        with self._transaction() as session:
            row, _ = self._owned(session, lease)
            if row.kind != "correlate_trace":
                raise LeaseLost("lease is not a correlation job")
            reference = self._validate_correlation(session, row)
            return CorrelationSnapshot(
                trace_id=reference.trace_id,
                expected_span_id=reference.span_id or "",
                deadline_at=reference.deadline_at,
                first_checked_at=reference.first_checked_at,
                lookup_attempt_count=reference.lookup_attempt_count,
                status=reference.status,
            )

    def record_trace_lookup(self, lease: Lease, result: TraceLookup) -> CorrelationUpdate:
        """Persist one safe lookup and terminalize the leased job atomically."""
        with self._transaction() as session:
            row, now = self._owned(session, lease)
            if row.kind != "correlate_trace":
                raise LeaseLost("lease is not a correlation job")
            reference = self._validate_correlation(session, row)
            if result.trace_id != reference.trace_id:
                raise LeaseLost("lookup identity does not match reference")
            if reference.lookup_attempt_count >= 7:
                raise LeaseLost("lookup budget exhausted")
            if reference.last_checked_at is not None and now < reference.last_checked_at:
                raise LeaseLost("lookup timestamp moved backwards")

            lookup_count = reference.lookup_attempt_count + 1
            reference.first_checked_at = reference.first_checked_at or now
            reference.last_checked_at = now
            reference.lookup_attempt_count = lookup_count
            reference.status = result.status.value
            reference.last_error_code = result.error_code.value if result.error_code else None
            reference.evidence_json = validate_evidence(
                {
                    "schema_version": 1,
                    "primary_span_found": result.client_span_id is not None,
                    "trace_span_count": result.trace_span_count,
                    "error_span_count": result.error_span_count,
                    "services": [
                        {
                            "name": service.name,
                            "version": service.version,
                            "environment": service.environment,
                            "revision": service.revision,
                        }
                        for service in result.services
                    ],
                    "deployments": [],
                    "linked_match_count": 0,
                    "context_continuity": result.context_continuity.value,
                    "comparison_anchor": None,
                }
            )
            terminal_status = result.status.value
            terminal = result.status is TraceLookupStatus.AVAILABLE
            if now >= reference.deadline_at:
                terminal = True
                if result.status is TraceLookupStatus.MISSING:
                    terminal_status = "expired"
                elif result.status is TraceLookupStatus.TEMPO_UNAVAILABLE:
                    terminal_status = "tempo_unavailable"
                else:
                    terminal_status = result.status.value
            reference.status = terminal_status
            reference.updated_at = now
            if terminal:
                validate_transition(JobState(row.state), JobState.SUCCEEDED)
                row.state = JobState.SUCCEEDED
                row.finished_at = now
                self._clear_lease(row)
            return CorrelationUpdate(terminal, terminal_status, lookup_count)

    def finalize_correlation(self, lease: Lease) -> CorrelationUpdate:
        """Close a lookup window without inventing an outage or trace result."""
        with self._transaction() as session:
            row, now = self._owned(session, lease)
            if row.kind != "correlate_trace":
                raise LeaseLost("lease is not a correlation job")
            reference = self._validate_correlation(session, row)
            if now < reference.deadline_at and reference.lookup_attempt_count < 7:
                raise LeaseLost("correlation window remains open")
            if reference.status == "missing":
                reference.status = "expired"
            elif reference.status == "pending":
                reference.status = "expired"
            reference.updated_at = now
            validate_transition(JobState(row.state), JobState.SUCCEEDED)
            row.state = JobState.SUCCEEDED
            row.finished_at = now
            self._clear_lease(row)
            return CorrelationUpdate(True, reference.status, reference.lookup_attempt_count)

    def _dead(self, session: Session, row: JobRow, code: ErrorCode, now: datetime) -> None:
        validate_transition(JobState(row.state), JobState.DEAD)
        row.state = JobState.DEAD
        row.last_error_code = code
        row.finished_at = now
        self._clear_lease(row)
        if row.kind == "correlate_trace":
            reference = self._validate_correlation(session, row)
            if reference.lookup_attempt_count == 0:
                reference.status = "tempo_unavailable"
                reference.last_error_code = "correlation_delivery_exhausted"
                reference.updated_at = now
            return
        execution = self._subject(session, row)
        if self._fail_pending_evaluation(session, execution, now):
            return
        if execution.status in {"queued", "running"}:
            execution.status = "failed"
            execution.verdict = "not_evaluated"
            execution.finished_at = now

    @staticmethod
    def _fail_pending_evaluation(session: Session, execution: ExecutionRow, now: datetime) -> bool:
        if execution.result_contract_version != 1:
            return False
        items = list(
            session.scalars(
                select(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution.id)
                .order_by(ExecutionItemRow.ordinal)
                .with_for_update()
            )
        )
        attempts = list(
            session.scalars(
                select(TestAttemptRow)
                .join(ExecutionItemRow, TestAttemptRow.execution_item_id == ExecutionItemRow.id)
                .where(ExecutionItemRow.execution_id == execution.id)
                .order_by(TestAttemptRow.sequence.desc())
                .with_for_update()
            )
        )
        latest: dict[UUID, TestAttemptRow] = {}
        for attempt in attempts:
            latest.setdefault(attempt.execution_item_id, attempt)
        pending: ExecutionItemRow | None = None
        pending_attempt: TestAttemptRow | None = None
        for item in items:
            candidate = latest.get(item.id)
            if (
                item.status == "running"
                and candidate is not None
                and candidate.result_contract_version == 1
                and candidate.state == "response_received"
            ):
                pending = item
                pending_attempt = candidate
                break
        if pending is None or pending_attempt is None:
            return False
        pending_attempt.state = "failed"
        pending_attempt.verdict = "inconclusive"
        pending_attempt.evaluation_error_code = "platform_evaluation_failure"
        pending_attempt.finished_at = now
        pending_attempt.duration_ms = max(
            0, int((now - pending_attempt.created_at).total_seconds() * 1000)
        )
        pending.status = "failed"
        pending.verdict = "inconclusive"
        pending.finished_at = now
        for item in items:
            if item.ordinal > pending.ordinal and item.status == "pending":
                item.status = "skipped"
                item.verdict = "not_evaluated"
                item.finished_at = now
        execution.status = "failed"
        execution.verdict = "inconclusive"
        execution.finished_at = now
        return True

    @staticmethod
    def _clear_lease(row: JobRow) -> None:
        row.lease_owner = None
        row.lease_token = None
        row.lease_expires_at = None
