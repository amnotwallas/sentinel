"""PostgreSQL checkpoints for deterministic, fenced execution orchestration."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.execution.attempts import AttemptRecord, ResponseArtifact
from sentinel.execution.domain import (
    AttemptState,
    DispatchCertainty,
    ErrorCode,
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
    BaselineActivationRow,
    BaselineRow,
    EnvironmentRevisionRow,
    ExecutionItemRow,
    ExecutionRow,
    JobRow,
    ResponseArtifactRow,
    TestAttemptRow,
    TestCaseRevisionRow,
)
from sentinel.persistence.regression import (
    BaselineComparisonInput,
    BoundedEvidence,
    EvaluationInput,
    PostgresEvaluationPersistence,
)
from sentinel.persistence.trace_references import TraceReferenceRepository
from sentinel.regression.evaluator import (
    BaselineCandidate,
    BaselineState,
    EvaluationResult,
    Verdict,
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
_VERDICT_PRECEDENCE = (
    "inconclusive",
    "baseline_required",
    "functional_regression",
    "performance_warning",
    "observed_change",
    "not_evaluated",
    "passed",
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
                    result_contract_version=item.result_contract_version,
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
            artifact = None
            if attempt.state == AttemptState.RESPONSE_RECEIVED:
                artifact_row = session.get(ResponseArtifactRow, attempt.id)
                if artifact_row is None:
                    raise OrchestrationConflict("response artifact missing")
                artifact = ResponseArtifact(
                    attempt_id=artifact_row.attempt_id,
                    status_code=artifact_row.status_code,
                    headers=artifact_row.headers,
                    body_kind=artifact_row.body_kind,
                    body_content=artifact_row.body_content,
                    source_bytes_captured=artifact_row.source_bytes_captured,
                    truncated=artifact_row.truncated,
                    redaction_unavailable=artifact_row.redaction_unavailable,
                    recorded_at=artifact_row.recorded_at,
                    expires_at=artifact_row.expires_at,
                )
            baseline = None
            baseline_activation_id = item.baseline_activation_id
            baseline_id = item.baseline_id
            baseline_version = None
            baseline_policy_fingerprint = None
            if baseline_activation_id is not None and baseline_id is not None:
                activation = session.scalar(
                    select(BaselineActivationRow).where(
                        BaselineActivationRow.id == baseline_activation_id,
                        BaselineActivationRow.baseline_id == baseline_id,
                        BaselineActivationRow.test_case_id == item.test_case_id,
                        BaselineActivationRow.environment_id == execution.environment_id,
                        BaselineActivationRow.project_id == item.project_id,
                    )
                )
                baseline_row = session.scalar(
                    select(BaselineRow).where(
                        BaselineRow.id == baseline_id,
                        BaselineRow.test_case_id == item.test_case_id,
                        BaselineRow.environment_id == execution.environment_id,
                        BaselineRow.project_id == item.project_id,
                    )
                )
                if activation is None or baseline_row is None:
                    raise OrchestrationConflict("pinned baseline missing")
                selected_values = baseline_row.selected_values
                raw_values = selected_values.get("values")
                if not isinstance(raw_values, list):
                    raise OrchestrationConflict("pinned baseline values malformed")
                values: dict[str, object] = {}
                for entry in raw_values:
                    if not isinstance(entry, dict) or not isinstance(entry.get("rule_id"), str):
                        raise OrchestrationConflict("pinned baseline values malformed")
                    values[entry["rule_id"]] = entry.get("value")
                baseline = BaselineCandidate(
                    policy_fingerprint=baseline_row.policy_fingerprint,
                    values=values,
                )
                baseline_version = baseline_row.version
                baseline_policy_fingerprint = baseline_row.policy_fingerprint
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
                result_contract_version=attempt.result_contract_version,
                response_artifact=artifact,
                baseline=baseline,
                baseline_activation_id=baseline_activation_id,
                baseline_id=baseline_id,
                baseline_version=baseline_version,
                baseline_policy_fingerprint=baseline_policy_fingerprint,
                snapshot_at=now,
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
            TraceReferenceRepository.create_primary(
                session,
                attempt=row,
                item=item,
                execution=execution,
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
            TraceReferenceRepository.finalize_primary(
                session, attempt=row, terminal_at=now, execution_id=execution.id
            )
            if row.result_contract_version == 0:
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
            TraceReferenceRepository.finalize_primary(
                session, attempt=row, terminal_at=now, execution_id=execution.id
            )
            return self._aggregate(job, execution, items, now)

    def persist_evaluation(
        self,
        attempt_id: UUID,
        lease: Lease,
        result: EvaluationResult,
        *,
        evaluation_ids: Sequence[UUID],
    ) -> bool:
        if len(evaluation_ids) != len(result.evaluations):
            raise OrchestrationConflict("evaluation identity count mismatch")
        with self._transaction() as session:
            job, execution, items, now = self._lock_execution(session, lease)
            self._require_running(execution)
            item, row = self._lock_attempt(session, items, attempt_id)
            if row.result_contract_version != 1:
                raise OrchestrationConflict("version-0 attempt cannot be evaluated")
            if row.state == AttemptState.EVALUATED:
                return self._aggregate(job, execution, items, now)
            if row.state != AttemptState.RESPONSE_RECEIVED or item.status != "running":
                raise OrchestrationConflict("attempt is not awaiting evaluation")

            baseline_version = None
            baseline_activation_id = None
            baseline_id = None
            policy_fingerprint = None
            if result.baseline_state in {BaselineState.COMPATIBLE, BaselineState.INCOMPATIBLE}:
                if item.baseline_activation_id is None or item.baseline_id is None:
                    raise OrchestrationConflict("baseline comparison pin is missing")
                baseline = session.scalar(
                    select(BaselineRow).where(
                        BaselineRow.id == item.baseline_id,
                        BaselineRow.test_case_id == item.test_case_id,
                        BaselineRow.environment_id == execution.environment_id,
                        BaselineRow.project_id == item.project_id,
                    )
                )
                if baseline is None:
                    raise OrchestrationConflict("baseline comparison candidate is missing")
                baseline_activation_id = item.baseline_activation_id
                baseline_id = item.baseline_id
                baseline_version = baseline.version
                policy_fingerprint = baseline.policy_fingerprint

            comparison_state = cast(
                Literal["not_requested", "missing", "incompatible", "compatible"],
                {
                    BaselineState.NOT_REQUESTED: "not_requested",
                    BaselineState.MISSING: "missing",
                    BaselineState.INCOMPATIBLE: "incompatible",
                    BaselineState.COMPATIBLE: "compatible",
                }[result.baseline_state],
            )
            comparison = BaselineComparisonInput(
                state=comparison_state,
                baseline_activation_id=baseline_activation_id,
                baseline_id=baseline_id,
                baseline_version=baseline_version,
                policy_fingerprint=policy_fingerprint,
                checked_at=now,
            )
            evaluations = tuple(
                EvaluationInput(
                    id=evaluation_id,
                    ordinal=evaluation.ordinal,
                    kind=evaluation.kind.value,
                    rule_id=UUID(evaluation.rule_id) if evaluation.rule_id is not None else None,
                    severity=evaluation.severity.value,
                    outcome=evaluation.outcome.value,
                    message_code=evaluation.message_code.value,
                    expected=BoundedEvidence(evaluation.expected, evaluation.evidence_omitted),
                    actual=BoundedEvidence(evaluation.actual, evaluation.evidence_omitted),
                    created_at=now,
                )
                for evaluation_id, evaluation in zip(
                    evaluation_ids, result.evaluations, strict=True
                )
            )
            PostgresEvaluationPersistence.add_result(
                session,
                attempt_id=attempt_id,
                comparison=comparison,
                evaluations=evaluations,
            )
            row.state = AttemptState.EVALUATED
            row.verdict = result.verdict.value
            row.evaluation_error_code = None
            self._finish_item(item, "completed", result.verdict.value, now)
            return self._aggregate(job, execution, items, now)

    def fail_evaluation(self, attempt_id: UUID, lease: Lease) -> None:
        with self._transaction() as session:
            job, execution, items, now = self._lock_execution(session, lease)
            self._require_running(execution)
            item, row = self._lock_attempt(session, items, attempt_id)
            if row.state == AttemptState.FAILED and row.evaluation_error_code == (
                "platform_evaluation_failure"
            ):
                return
            if row.result_contract_version != 1 or row.state != AttemptState.RESPONSE_RECEIVED:
                raise OrchestrationConflict("attempt is not awaiting evaluation failure")
            row.state = AttemptState.FAILED
            row.verdict = Verdict.INCONCLUSIVE.value
            row.evaluation_error_code = "platform_evaluation_failure"
            row.finished_at = now
            self._finish_item(item, "failed", Verdict.INCONCLUSIVE.value, now)
            for remaining in items:
                if remaining.ordinal > item.ordinal and remaining.status == "pending":
                    self._finish_item(remaining, "skipped", "not_evaluated", now)
            execution.status = "failed"
            execution.verdict = Verdict.INCONCLUSIVE.value
            execution.finished_at = now
            job.state = JobState.DEAD
            job.last_error_code = ErrorCode.HANDLER_FAILED
            job.finished_at = now
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None

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
                result_contract_version=predecessor.result_contract_version,
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
            TraceReferenceRepository.finalize_primary(
                session, attempt=predecessor, terminal_at=now, execution_id=execution.id
            )
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
            TraceReferenceRepository.finalize_primary(
                session, attempt=row, terminal_at=now, execution_id=execution.id
            )
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
                TraceReferenceRepository.finalize_primary(
                    session, attempt=row, terminal_at=now, execution_id=execution.id
                )
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
            TraceReferenceRepository.finalize_primary(
                session, attempt=row, terminal_at=now, execution_id=execution.id
            )
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
        verdict = next(
            (
                candidate
                for candidate in _VERDICT_PRECEDENCE
                if any(item.verdict == candidate for item in items)
            ),
            "not_evaluated",
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
