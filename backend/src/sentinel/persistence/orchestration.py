"""PostgreSQL checkpoints for deterministic, fenced execution orchestration."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.attempts import AttemptRecord, ResponseArtifact
from sentinel.execution.domain import (
    AttemptState,
    DispatchCertainty,
    InfrastructureFailure,
    JobState,
    Lease,
    LeaseLost,
    PreparationErrorCode,
    RedirectRejectionCode,
    TransportOutcome,
)
from sentinel.execution.ports import PinnedAttempt
from sentinel.persistence.attempts import AttemptConflict, AttemptNotFound, PostgresAttemptStore
from sentinel.persistence.models import (
    EnvironmentRevisionRow,
    ExecutionItemRow,
    ExecutionRow,
    JobRow,
    ResponseArtifactRow,
    TestAttemptRow,
    TestCaseRevisionRow,
)

_TERMINAL_ITEM_STATES = frozenset({"completed", "indeterminate", "failed", "skipped"})
_NOT_SENT_OUTCOMES = frozenset(
    {
        TransportOutcome.DNS_FAILURE,
        TransportOutcome.CONNECT_TIMEOUT,
        TransportOutcome.CONNECTION_FAILURE,
        TransportOutcome.TLS_FAILURE,
        TransportOutcome.TARGET_DENIED,
    }
)
_RECEIVED_FAILURE_OUTCOMES = frozenset(
    {
        TransportOutcome.REDIRECT_DENIED,
        TransportOutcome.READ_TIMEOUT,
        TransportOutcome.READ_FAILURE,
        TransportOutcome.DNS_FAILURE,
        TransportOutcome.CONNECT_TIMEOUT,
        TransportOutcome.CONNECTION_FAILURE,
        TransportOutcome.TLS_FAILURE,
        TransportOutcome.TARGET_DENIED,
    }
)
_POSSIBLY_SENT_OUTCOMES = frozenset(
    {
        TransportOutcome.WRITE_TIMEOUT,
        TransportOutcome.WRITE_FAILURE,
        TransportOutcome.READ_TIMEOUT,
        TransportOutcome.READ_FAILURE,
        TransportOutcome.TOTAL_TIMEOUT,
        TransportOutcome.INDETERMINATE,
    }
)
_ARTIFACT_FAILURE_OUTCOMES = frozenset(
    {
        TransportOutcome.REDIRECT_DENIED,
        TransportOutcome.READ_TIMEOUT,
        TransportOutcome.READ_FAILURE,
    }
)


class OrchestrationConflict(ValueError):
    pass


class PostgresOrchestrationStore:
    """Own each short checkpoint transaction; target I/O happens in its caller."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
        artifact_retention: timedelta = timedelta(days=7),
    ) -> None:
        self.sessions = sessions
        self.clock = clock
        self.artifact_retention = artifact_retention

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        try:
            with self.sessions.begin() as session:
                yield session
        except OperationalError:
            raise InfrastructureFailure("database_operation_failed") from None

    def _now(self, session: Session) -> datetime:
        if self.clock is not None:
            return self.clock()
        value = session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("PostgreSQL clock unavailable")
        return value

    def _lock_execution(
        self, session: Session, lease: Lease
    ) -> tuple[JobRow, ExecutionRow, list[ExecutionItemRow], datetime]:
        job = session.scalar(select(JobRow).where(JobRow.id == lease.job_id).with_for_update())
        now = self._now(session)
        if (
            job is None
            or job.kind != "execute_execution"
            or job.subject_id != lease.subject_id
            or job.state != JobState.LEASED
            or job.lease_owner != lease.owner
            or job.lease_token != lease.token
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            raise LeaseLost("lease no longer owns execution")
        execution = session.scalar(
            select(ExecutionRow).where(ExecutionRow.id == lease.subject_id).with_for_update()
        )
        if execution is None:
            raise OrchestrationConflict("execution subject missing")
        items = list(
            session.scalars(
                select(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution.id)
                .order_by(ExecutionItemRow.ordinal)
                .with_for_update()
            )
        )
        if not items:
            raise OrchestrationConflict("execution items missing")
        return job, execution, items, now

    @staticmethod
    def _lock_attempt(
        session: Session, items: list[ExecutionItemRow], attempt_id: UUID
    ) -> tuple[ExecutionItemRow, TestAttemptRow]:
        item_by_id = {item.id: item for item in items}
        row = session.scalar(
            select(TestAttemptRow).where(TestAttemptRow.id == attempt_id).with_for_update()
        )
        if row is None:
            raise AttemptNotFound
        item = item_by_id.get(row.execution_item_id)
        if item is None:
            raise LeaseLost("attempt is outside leased execution")
        return item, row

    @staticmethod
    def _attempt(row: TestAttemptRow) -> AttemptRecord:
        return PostgresAttemptStore._record(row)

    def acquire_next(self, lease: Lease, *, attempt_id: UUID) -> PinnedAttempt | None:
        with self._transaction() as session:
            _job, execution, items, now = self._lock_execution(session, lease)
            if execution.status == "queued":
                execution.status = "running"
                execution.started_at = now
            elif execution.status != "running":
                raise LeaseLost("execution is terminal")
            item = next(
                (candidate for candidate in items if candidate.status not in _TERMINAL_ITEM_STATES),
                None,
            )
            if item is None:
                return None
            attempt: TestAttemptRow
            if item.status == "pending":
                item.status = "running"
                item.started_at = now
                attempt = TestAttemptRow(
                    id=attempt_id,
                    execution_item_id=item.id,
                    sequence=1,
                    state=AttemptState.PREPARED,
                    dispatch_certainty=DispatchCertainty.NOT_STARTED,
                    created_at=now,
                    included_in_verdict=True,
                )
                session.add(attempt)
                session.flush()
            elif item.status == "running":
                existing_attempt = session.scalar(
                    select(TestAttemptRow)
                    .where(TestAttemptRow.execution_item_id == item.id)
                    .order_by(TestAttemptRow.sequence.desc())
                    .with_for_update()
                    .limit(1)
                )
                if existing_attempt is None:
                    raise OrchestrationConflict("running item has no attempt")
                attempt = existing_attempt
            else:
                raise OrchestrationConflict("unexpected item state")

            environment = session.scalar(
                select(EnvironmentRevisionRow).where(
                    EnvironmentRevisionRow.id == execution.environment_revision_id,
                    EnvironmentRevisionRow.environment_id == execution.environment_id,
                )
            )
            revision = session.scalar(
                select(TestCaseRevisionRow).where(
                    TestCaseRevisionRow.id == item.test_case_revision_id,
                    TestCaseRevisionRow.test_case_id == item.test_case_id,
                    TestCaseRevisionRow.version == item.test_case_revision_version,
                )
            )
            if environment is None or revision is None:
                raise OrchestrationConflict("pinned revision missing")
            definition = copy.deepcopy(revision.definition)
            allow_unsafe = (
                isinstance(definition, dict) and definition.get("allow_unsafe_replay") is True
            )
            acknowledged = (
                allow_unsafe
                and revision.unsafe_replay_acknowledgement == "duplicate_effects_possible"
                and revision.unsafe_replay_acknowledged_at is not None
            )
            return PinnedAttempt(
                execution.id,
                self._attempt(attempt),
                copy.deepcopy(environment.definition),
                definition,
                acknowledged,
            )

    def checkpoint_dispatch(
        self,
        attempt_id: UUID,
        lease: Lease,
        *,
        fingerprint: str,
        trace_id: str,
        span_id: str,
    ) -> AttemptRecord:
        with self._transaction() as session:
            _job, execution, items, now = self._lock_execution(session, lease)
            if execution.status != "running":
                raise OrchestrationConflict("execution is not running")
            item, row = self._lock_attempt(session, items, attempt_id)
            if item.status != "running":
                raise OrchestrationConflict("item is not running")
            PostgresAttemptStore._set_dispatch(
                row,
                fingerprint=fingerprint,
                trace_id=trace_id,
                span_id=span_id,
                now=now,
            )
            return self._attempt(row)

    def fail_preparation(self, attempt_id: UUID, lease: Lease, code: PreparationErrorCode) -> bool:
        with self._transaction() as session:
            job, execution, items, now = self._lock_execution(session, lease)
            self._require_running(execution)
            item, row = self._lock_attempt(session, items, attempt_id)
            if row.state != AttemptState.PREPARED or item.status != "running":
                raise OrchestrationConflict("preparation checkpoint state changed")
            row.state = AttemptState.FAILED
            row.preparation_error_code = code
            row.finished_at = now
            row.duration_ms = self._duration(row, now)
            self._finish_item(item, "failed", "not_evaluated", now)
            return self._aggregate(job, execution, items, now)

    def record_response(
        self,
        attempt_id: UUID,
        lease: Lease,
        artifact: ResponseArtifact,
        *,
        outcome: TransportOutcome,
    ) -> bool:
        if artifact.attempt_id != attempt_id:
            raise AttemptConflict("artifact attempt mismatch")
        if outcome not in {
            TransportOutcome.RESPONSE_RECEIVED,
            TransportOutcome.RESPONSE_LIMIT_EXCEEDED,
        }:
            raise AttemptConflict("invalid accepted response outcome")
        if artifact.truncated != (outcome == TransportOutcome.RESPONSE_LIMIT_EXCEEDED):
            raise AttemptConflict("response outcome does not match bounded capture")
        self._validate_artifact(artifact)
        with self._transaction() as session:
            job, execution, items, now = self._lock_execution(session, lease)
            self._require_running(execution)
            item, row = self._lock_attempt(session, items, attempt_id)
            self._require_dispatching(item, row)
            session.add(self._artifact_row(artifact))
            row.state = AttemptState.RESPONSE_RECEIVED
            row.dispatch_certainty = DispatchCertainty.RESPONSE_RECEIVED
            row.transport_outcome = outcome
            row.response_recorded_at = artifact.recorded_at
            row.finished_at = now
            row.duration_ms = self._duration(row, now)
            self._finish_item(item, "completed", "not_evaluated", now)
            return self._aggregate(job, execution, items, now)

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
    ) -> bool:
        self._validate_transport_failure(
            attempt_id,
            outcome=outcome,
            certainty=certainty,
            not_sent_proof=not_sent_proof,
            redirect_code=redirect_code,
            artifact=artifact,
        )
        with self._transaction() as session:
            job, execution, items, now = self._lock_execution(session, lease)
            self._require_running(execution)
            item, row = self._lock_attempt(session, items, attempt_id)
            self._require_dispatching(item, row)
            if artifact is not None:
                session.add(self._artifact_row(artifact))
                row.response_recorded_at = artifact.recorded_at
            row.state = AttemptState.TRANSPORT_FAILED
            row.dispatch_certainty = certainty
            row.transport_outcome = outcome
            row.redirect_rejection_code = redirect_code
            row.finished_at = now
            row.duration_ms = self._duration(row, now)
            if certainty == DispatchCertainty.NOT_SENT and outcome in {
                TransportOutcome.TARGET_DENIED,
                TransportOutcome.TLS_FAILURE,
            }:
                self._finish_item(item, "failed", "not_evaluated", now)
            else:
                self._finish_item(item, "completed", "inconclusive", now)
            return self._aggregate(job, execution, items, now)

    def schedule_replay(
        self, attempt_id: UUID, lease: Lease, *, successor_id: UUID
    ) -> AttemptRecord:
        with self._transaction() as session:
            _job, execution, items, now = self._lock_execution(session, lease)
            if execution.status != "running":
                raise OrchestrationConflict("execution is not running")
            item, predecessor = self._lock_attempt(session, items, attempt_id)
            if item.status != "running":
                raise OrchestrationConflict("item is not running")
            if predecessor.state == AttemptState.REPLAY_SCHEDULED:
                if predecessor.replay_successor_id is None:
                    raise OrchestrationConflict("replay successor missing")
                successor = session.scalar(
                    select(TestAttemptRow)
                    .where(TestAttemptRow.id == predecessor.replay_successor_id)
                    .with_for_update()
                )
                if successor is None:
                    raise OrchestrationConflict("replay successor missing")
                return self._attempt(successor)
            if predecessor.state != AttemptState.DISPATCHING:
                raise OrchestrationConflict("attempt is not recoverable")
            successor = TestAttemptRow(
                id=successor_id,
                execution_item_id=item.id,
                sequence=predecessor.sequence + 1,
                state=AttemptState.PREPARED,
                dispatch_certainty=DispatchCertainty.NOT_STARTED,
                created_at=now,
                included_in_verdict=True,
            )
            session.add(successor)
            session.flush()
            predecessor.state = AttemptState.REPLAY_SCHEDULED
            predecessor.replay_successor_id = successor.id
            predecessor.included_in_verdict = False
            predecessor.finished_at = now
            predecessor.duration_ms = self._duration(predecessor, now)
            session.flush()
            return self._attempt(successor)

    def mark_indeterminate(self, attempt_id: UUID, lease: Lease) -> None:
        with self._transaction() as session:
            job, execution, items, now = self._lock_execution(session, lease)
            self._require_running(execution)
            item, row = self._lock_attempt(session, items, attempt_id)
            self._require_dispatching(item, row)
            row.state = AttemptState.INDETERMINATE
            row.transport_outcome = TransportOutcome.INDETERMINATE
            row.finished_at = now
            row.duration_ms = self._duration(row, now)
            self._finish_item(item, "indeterminate", "inconclusive", now)
            for remaining in items:
                if remaining.ordinal <= item.ordinal:
                    continue
                if remaining.status == "pending":
                    self._finish_item(remaining, "skipped", "not_evaluated", now)
                elif remaining.status == "running":
                    raise OrchestrationConflict("later suite item is already running")
            if not self._aggregate(job, execution, items, now):
                raise OrchestrationConflict("ambiguity did not terminate execution")

    def resume_terminal(self, attempt_id: UUID, lease: Lease) -> bool:
        with self._transaction() as session:
            job, execution, items, now = self._lock_execution(session, lease)
            self._require_running(execution)
            item, row = self._lock_attempt(session, items, attempt_id)
            if item.status in _TERMINAL_ITEM_STATES:
                return self._aggregate(job, execution, items, now)
            if item.status != "running":
                raise OrchestrationConflict("item is not resumable")
            if row.state == AttemptState.RESPONSE_RECEIVED:
                self._finish_item(item, "completed", "not_evaluated", now)
            elif row.state == AttemptState.TRANSPORT_FAILED:
                policy_failure = (
                    row.dispatch_certainty == DispatchCertainty.NOT_SENT
                    and row.transport_outcome
                    in {TransportOutcome.TARGET_DENIED, TransportOutcome.TLS_FAILURE}
                )
                if policy_failure:
                    self._finish_item(item, "failed", "not_evaluated", now)
                else:
                    self._finish_item(item, "completed", "inconclusive", now)
            elif row.state == AttemptState.FAILED:
                self._finish_item(item, "failed", "not_evaluated", now)
            elif row.state == AttemptState.INDETERMINATE:
                self._finish_item(item, "indeterminate", "inconclusive", now)
            else:
                raise OrchestrationConflict("attempt is not terminal")
            return self._aggregate(job, execution, items, now)

    def complete_execution(self, lease: Lease) -> None:
        with self._transaction() as session:
            job, execution, items, now = self._lock_execution(session, lease)
            self._require_running(execution)
            if not self._aggregate(job, execution, items, now):
                raise OrchestrationConflict("execution still has runnable items")

    @staticmethod
    def _duration(row: TestAttemptRow, now: datetime) -> int:
        return max(0, int((now - row.created_at).total_seconds() * 1000))

    @staticmethod
    def _require_dispatching(item: ExecutionItemRow, row: TestAttemptRow) -> None:
        if item.status != "running" or row.state != AttemptState.DISPATCHING:
            raise OrchestrationConflict("dispatch checkpoint state changed")
        if row.dispatch_certainty != DispatchCertainty.POSSIBLY_SENT:
            raise OrchestrationConflict("dispatch certainty changed")

    @staticmethod
    def _require_running(execution: ExecutionRow) -> None:
        if execution.status != "running":
            raise OrchestrationConflict("execution is not running")

    @staticmethod
    def _finish_item(item: ExecutionItemRow, status: str, verdict: str, now: datetime) -> None:
        if item.status != "running" and not (item.status == "pending" and status == "skipped"):
            raise OrchestrationConflict("item terminal checkpoint state changed")
        item.status = status
        item.verdict = verdict
        item.finished_at = now

    @staticmethod
    def _succeed(job: JobRow, execution: ExecutionRow, verdict: str, now: datetime) -> None:
        execution.status = "completed"
        execution.verdict = verdict
        execution.finished_at = now
        job.state = JobState.SUCCEEDED
        job.finished_at = now
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None

    def _aggregate(
        self,
        job: JobRow,
        execution: ExecutionRow,
        items: list[ExecutionItemRow],
        now: datetime,
    ) -> bool:
        if any(item.status not in _TERMINAL_ITEM_STATES for item in items):
            return False
        verdict = (
            "inconclusive"
            if any(item.verdict == "inconclusive" for item in items)
            else "not_evaluated"
        )
        self._succeed(job, execution, verdict, now)
        return True

    def _validate_artifact(self, artifact: ResponseArtifact) -> None:
        if artifact.expires_at > artifact.recorded_at + self.artifact_retention:
            raise AttemptConflict("artifact retention exceeds policy")
        if artifact.body_kind not in {None, "json", "text", "bytes"}:
            raise AttemptConflict("invalid artifact body kind")
        if (artifact.body_kind is None) != (artifact.body_content is None):
            raise AttemptConflict("invalid artifact body shape")

    def _validate_transport_failure(
        self,
        attempt_id: UUID,
        *,
        outcome: TransportOutcome,
        certainty: DispatchCertainty,
        not_sent_proof: str | None,
        redirect_code: RedirectRejectionCode | None,
        artifact: ResponseArtifact | None,
    ) -> None:
        if (
            outcome
            in {
                TransportOutcome.RESPONSE_RECEIVED,
                TransportOutcome.RESPONSE_LIMIT_EXCEEDED,
            }
            or certainty == DispatchCertainty.NOT_STARTED
        ):
            raise AttemptConflict("invalid transport failure certainty")
        if certainty == DispatchCertainty.NOT_SENT:
            if outcome not in _NOT_SENT_OUTCOMES or not_sent_proof != outcome.value:
                raise AttemptConflict("not_sent requires positive phase proof")
        elif certainty == DispatchCertainty.POSSIBLY_SENT:
            if outcome not in _POSSIBLY_SENT_OUTCOMES or not_sent_proof is not None:
                raise AttemptConflict("invalid possibly-sent failure outcome")
        elif certainty == DispatchCertainty.RESPONSE_RECEIVED:
            if outcome not in _RECEIVED_FAILURE_OUTCOMES or not_sent_proof is not None:
                raise AttemptConflict("invalid response-received failure outcome")
        else:
            raise AttemptConflict("invalid response-received failure outcome")
        if (outcome == TransportOutcome.REDIRECT_DENIED) != (redirect_code is not None):
            raise AttemptConflict("redirect outcome requires exact rejection code")
        if artifact is not None:
            if artifact.attempt_id != attempt_id:
                raise AttemptConflict("artifact attempt mismatch")
            if not (
                certainty == DispatchCertainty.RESPONSE_RECEIVED
                and outcome in _ARTIFACT_FAILURE_OUTCOMES
            ):
                raise AttemptConflict("artifact is only valid for received redirect evidence")
            self._validate_artifact(artifact)
        elif certainty == DispatchCertainty.RESPONSE_RECEIVED and outcome in {
            TransportOutcome.REDIRECT_DENIED,
            TransportOutcome.READ_TIMEOUT,
            TransportOutcome.READ_FAILURE,
        }:
            raise AttemptConflict("received failure evidence is missing")

    @staticmethod
    def _artifact_row(artifact: ResponseArtifact) -> ResponseArtifactRow:
        return ResponseArtifactRow(
            attempt_id=artifact.attempt_id,
            status_code=artifact.status_code,
            headers=artifact.headers,
            body_kind=artifact.body_kind,
            body_content=artifact.body_content,
            source_bytes_captured=artifact.source_bytes_captured,
            truncated=artifact.truncated,
            redaction_unavailable=artifact.redaction_unavailable,
            recorded_at=artifact.recorded_at,
            expires_at=artifact.expires_at,
        )
