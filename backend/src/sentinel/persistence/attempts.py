"""PostgreSQL attempt persistence with lease fencing at every checkpoint."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.attempts import AttemptRecord, ResponseArtifact
from sentinel.execution.domain import (
    AttemptState,
    DispatchCertainty,
    InvalidTransition,
    Lease,
    LeaseLost,
    PreparationErrorCode,
    RedirectRejectionCode,
    TransportOutcome,
    validate_attempt_transition,
)
from sentinel.persistence.models import (
    ExecutionItemRow,
    ExecutionRow,
    JobRow,
    ResponseArtifactRow,
    TestAttemptRow,
)
from sentinel.persistence.trace_references import TraceReferenceRepository


class AttemptNotFound(LookupError):
    pass


class AttemptConflict(ValueError):
    pass


class PostgresAttemptStore:
    """Short transactions; no secret-bearing request document is accepted."""

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

    def _now(self, session: Session) -> datetime:
        if self.clock is not None:
            return self.clock()
        value = session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("PostgreSQL clock unavailable")
        return value

    @staticmethod
    def _record(row: TestAttemptRow) -> AttemptRecord:
        return AttemptRecord(
            id=row.id,
            execution_item_id=row.execution_item_id,
            sequence=row.sequence,
            state=AttemptState(row.state),
            dispatch_certainty=DispatchCertainty(row.dispatch_certainty),
            request_fingerprint=row.request_fingerprint,
            created_at=row.created_at,
            dispatch_recorded_at=row.dispatch_recorded_at,
            response_recorded_at=row.response_recorded_at,
            finished_at=row.finished_at,
            duration_ms=row.duration_ms,
            transport_outcome=(
                TransportOutcome(row.transport_outcome)
                if row.transport_outcome is not None
                else None
            ),
            preparation_error_code=(
                PreparationErrorCode(row.preparation_error_code)
                if row.preparation_error_code is not None
                else None
            ),
            redirect_rejection_code=(
                RedirectRejectionCode(row.redirect_rejection_code)
                if row.redirect_rejection_code is not None
                else None
            ),
            replay_successor_id=row.replay_successor_id,
            primary_trace_id=row.primary_trace_id,
            client_span_id=row.client_span_id,
            included_in_verdict=row.included_in_verdict,
            result_contract_version=row.result_contract_version,
            verdict=row.verdict,
            evaluation_error_code=row.evaluation_error_code,
        )

    def create_prepared(
        self, execution_item_id: UUID, *, attempt_id: UUID, now: datetime | None = None
    ) -> AttemptRecord:
        try:
            with self.sessions.begin() as session:
                item = session.scalar(
                    select(ExecutionItemRow)
                    .where(ExecutionItemRow.id == execution_item_id)
                    .with_for_update()
                )
                if item is None:
                    raise AttemptNotFound
                sequence = session.scalar(
                    select(func.coalesce(func.max(TestAttemptRow.sequence), 0)).where(
                        TestAttemptRow.execution_item_id == execution_item_id
                    )
                )
                created = now or self._now(session)
                row = TestAttemptRow(
                    id=attempt_id,
                    execution_item_id=execution_item_id,
                    sequence=int(sequence or 0) + 1,
                    result_contract_version=item.result_contract_version,
                    state=AttemptState.PREPARED,
                    dispatch_certainty=DispatchCertainty.NOT_STARTED,
                    created_at=created,
                    included_in_verdict=True,
                )
                session.add(row)
                session.flush()
                return self._record(row)
        except (AttemptNotFound, IntegrityError, OperationalError):
            raise

    def get(self, attempt_id: UUID) -> AttemptRecord:
        with self.sessions() as session:
            row = session.get(TestAttemptRow, attempt_id)
            if row is None:
                raise AttemptNotFound
            return self._record(row)

    def _owned(
        self, session: Session, attempt_id: UUID, lease: Lease
    ) -> tuple[TestAttemptRow, datetime]:
        job = session.scalar(
            select(JobRow)
            .where(
                JobRow.id == lease.job_id,
                JobRow.state == "leased",
                JobRow.lease_owner == lease.owner,
                JobRow.lease_token == lease.token,
            )
            .with_for_update()
        )
        now = self._now(session)
        if (
            job is None
            or job.kind != "execute_execution"
            or job.subject_id != lease.subject_id
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            raise LeaseLost("lease expired")
        execution = session.scalar(
            select(ExecutionRow).where(ExecutionRow.id == job.subject_id).with_for_update()
        )
        if execution is None:
            raise LeaseLost("lease no longer owns attempt")
        item_id = session.scalar(
            select(TestAttemptRow.execution_item_id).where(TestAttemptRow.id == attempt_id)
        )
        if item_id is None:
            raise AttemptNotFound
        item = session.scalar(
            select(ExecutionItemRow)
            .where(
                ExecutionItemRow.id == item_id,
                ExecutionItemRow.execution_id == execution.id,
            )
            .with_for_update()
        )
        if item is None:
            raise LeaseLost("lease no longer owns attempt")
        row = session.scalar(
            select(TestAttemptRow)
            .where(TestAttemptRow.id == attempt_id, TestAttemptRow.execution_item_id == item.id)
            .with_for_update()
        )
        if row is None:
            raise AttemptNotFound
        return row, now

    @staticmethod
    def _trace_context(
        session: Session, row: TestAttemptRow, execution_id: UUID
    ) -> tuple[ExecutionItemRow, ExecutionRow]:
        item = session.scalar(
            select(ExecutionItemRow)
            .where(
                ExecutionItemRow.id == row.execution_item_id,
                ExecutionItemRow.execution_id == execution_id,
            )
            .with_for_update()
        )
        execution = session.scalar(
            select(ExecutionRow).where(ExecutionRow.id == execution_id).with_for_update()
        )
        if item is None or execution is None:
            raise LeaseLost("attempt is outside leased execution")
        return item, execution

    @staticmethod
    def _set_dispatch(
        row: TestAttemptRow, *, fingerprint: str, trace_id: str, span_id: str, now: datetime
    ) -> None:
        if row.state != AttemptState.PREPARED:
            raise InvalidTransition(f"invalid attempt transition: {row.state} -> dispatching")
        if (
            re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
            or re.fullmatch(r"[0-9a-f]{32}", trace_id) is None
            or re.fullmatch(r"[0-9a-f]{16}", span_id) is None
            or set(trace_id) == {"0"}
            or set(span_id) == {"0"}
        ):
            raise AttemptConflict("invalid dispatch identity")
        row.state = AttemptState.DISPATCHING
        row.dispatch_certainty = DispatchCertainty.POSSIBLY_SENT
        row.request_fingerprint = fingerprint
        row.primary_trace_id = trace_id
        row.client_span_id = span_id
        row.dispatch_recorded_at = now

    def checkpoint_dispatch(
        self, attempt_id: UUID, lease: Lease, *, fingerprint: str, trace_id: str, span_id: str
    ) -> AttemptRecord:
        with self.sessions.begin() as session:
            row, now = self._owned(session, attempt_id, lease)
            self._set_dispatch(
                row, fingerprint=fingerprint, trace_id=trace_id, span_id=span_id, now=now
            )
            item, execution = self._trace_context(session, row, lease.subject_id)
            TraceReferenceRepository.create_primary(
                session,
                attempt=row,
                item=item,
                execution=execution,
                trace_id=trace_id,
                span_id=span_id,
                now=now,
            )
            return self._record(row)

    def fail_preparation(
        self, attempt_id: UUID, lease: Lease, code: PreparationErrorCode
    ) -> AttemptRecord:
        with self.sessions.begin() as session:
            row, now = self._owned(session, attempt_id, lease)
            validate_attempt_transition(AttemptState(row.state), AttemptState.FAILED)
            if row.dispatch_certainty != DispatchCertainty.NOT_STARTED:
                raise AttemptConflict("dispatched attempt cannot become preparation failure")
            row.state = AttemptState.FAILED
            row.preparation_error_code = code
            row.finished_at = now
            row.duration_ms = max(0, int((now - row.created_at).total_seconds() * 1000))
            return self._record(row)

    def record_response(
        self,
        attempt_id: UUID,
        lease: Lease,
        artifact: ResponseArtifact,
        *,
        outcome: TransportOutcome,
    ) -> AttemptRecord:
        if artifact.attempt_id != attempt_id:
            raise AttemptConflict("artifact attempt mismatch")
        if outcome not in {
            TransportOutcome.RESPONSE_RECEIVED,
            TransportOutcome.RESPONSE_LIMIT_EXCEEDED,
        }:
            raise AttemptConflict("invalid accepted response outcome")
        if artifact.truncated != (outcome == TransportOutcome.RESPONSE_LIMIT_EXCEEDED):
            raise AttemptConflict("response outcome does not match bounded capture")
        if artifact.expires_at > artifact.recorded_at + self.artifact_retention:
            raise AttemptConflict("artifact retention exceeds policy")
        with self.sessions.begin() as session:
            row, now = self._owned(session, attempt_id, lease)
            validate_attempt_transition(AttemptState(row.state), AttemptState.RESPONSE_RECEIVED)
            if row.dispatch_certainty != DispatchCertainty.POSSIBLY_SENT:
                raise AttemptConflict("response requires dispatch certainty")
            session.add(
                ResponseArtifactRow(
                    attempt_id=attempt_id,
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
            )
            row.state = AttemptState.RESPONSE_RECEIVED
            row.dispatch_certainty = DispatchCertainty.RESPONSE_RECEIVED
            row.transport_outcome = outcome
            row.response_recorded_at = artifact.recorded_at
            row.finished_at = now
            row.duration_ms = max(0, int((now - row.created_at).total_seconds() * 1000))
            _item, execution = self._trace_context(session, row, lease.subject_id)
            TraceReferenceRepository.finalize_primary(
                session, attempt=row, terminal_at=now, execution_id=execution.id
            )
            return self._record(row)

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
    ) -> AttemptRecord:
        if artifact is not None and artifact.attempt_id != attempt_id:
            raise AttemptConflict("artifact attempt mismatch")
        if (
            outcome
            in {
                TransportOutcome.RESPONSE_RECEIVED,
                TransportOutcome.RESPONSE_LIMIT_EXCEEDED,
            }
            or certainty == DispatchCertainty.NOT_STARTED
        ):
            raise AttemptConflict("invalid transport failure certainty")
        if artifact is not None and not (
            certainty == DispatchCertainty.RESPONSE_RECEIVED
            and outcome
            in {
                TransportOutcome.REDIRECT_DENIED,
                TransportOutcome.READ_TIMEOUT,
                TransportOutcome.READ_FAILURE,
            }
        ):
            raise AttemptConflict("artifact is only valid for received redirect evidence")
        with self.sessions.begin() as session:
            row, now = self._owned(session, attempt_id, lease)
            validate_attempt_transition(AttemptState(row.state), AttemptState.TRANSPORT_FAILED)
            if (
                certainty == DispatchCertainty.NOT_SENT
                and row.dispatch_certainty != DispatchCertainty.POSSIBLY_SENT
            ):
                raise AttemptConflict("not_sent requires an existing dispatch checkpoint")
            proven_phases = {
                TransportOutcome.DNS_FAILURE: "dns_failure",
                TransportOutcome.CONNECT_TIMEOUT: "connect_timeout",
                TransportOutcome.CONNECTION_FAILURE: "connection_failure",
                TransportOutcome.TLS_FAILURE: "tls_failure",
                TransportOutcome.TARGET_DENIED: "target_denied",
            }
            if certainty == DispatchCertainty.NOT_SENT and not_sent_proof != proven_phases.get(
                outcome
            ):
                raise AttemptConflict("not_sent requires positive phase proof")
            if certainty == DispatchCertainty.NOT_SENT and outcome not in {
                TransportOutcome.DNS_FAILURE,
                TransportOutcome.CONNECT_TIMEOUT,
                TransportOutcome.CONNECTION_FAILURE,
                TransportOutcome.TLS_FAILURE,
                TransportOutcome.TARGET_DENIED,
            }:
                raise AttemptConflict("not_sent is not proven for this outcome")
            if certainty == DispatchCertainty.RESPONSE_RECEIVED and artifact is None:
                if outcome not in {
                    TransportOutcome.DNS_FAILURE,
                    TransportOutcome.CONNECT_TIMEOUT,
                    TransportOutcome.CONNECTION_FAILURE,
                    TransportOutcome.TLS_FAILURE,
                    TransportOutcome.TARGET_DENIED,
                }:
                    raise AttemptConflict("received certainty requires evidence")
            if artifact is not None and artifact.expires_at > (
                artifact.recorded_at + self.artifact_retention
            ):
                raise AttemptConflict("artifact retention exceeds policy")
            if artifact is not None:
                session.add(
                    ResponseArtifactRow(
                        attempt_id=attempt_id,
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
                )
                row.response_recorded_at = artifact.recorded_at
            row.state = AttemptState.TRANSPORT_FAILED
            row.dispatch_certainty = certainty
            row.transport_outcome = outcome
            row.redirect_rejection_code = redirect_code
            row.finished_at = now
            row.duration_ms = max(0, int((now - row.created_at).total_seconds() * 1000))
            _item, execution = self._trace_context(session, row, lease.subject_id)
            TraceReferenceRepository.finalize_primary(
                session, attempt=row, terminal_at=now, execution_id=execution.id
            )
            return self._record(row)
