from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.catalog.changes import ChangeEvent, ChangeEventKind, ChangeSubjectType, ChangeSummary
from sentinel.execution.attempts import AttemptRecord, ResponseArtifact
from sentinel.persistence.attempts import PostgresAttemptStore
from sentinel.persistence.models import (
    BaselineActivationRow,
    BaselineComparisonRow,
    BaselineRow,
    ChangeEventRow,
    EnvironmentRevisionRow,
    EnvironmentRow,
    EvaluationRow,
    ExecutionItemRow,
    ExecutionRow,
    IdempotencyRecordRow,
    JobRow,
    ProjectRow,
    ResponseArtifactRow,
    SuiteRevisionItemRow,
    SuiteRevisionRow,
    SuiteRow,
    TestAttemptRow,
    TestCaseRevisionRow,
    TestCaseRow,
)
from sentinel.regression.policy import canonical_json
from sentinel.regression.read_models import (
    ChangeRead,
    ComparisonRead,
    EvaluationRead,
    PromotionRead,
)


class ExecutionError(Exception):
    pass


class ExecutionResourceNotFound(ExecutionError):
    pass


class ExecutionIdempotencyConflict(ExecutionError):
    pass


class ExecutionValidationError(ExecutionError):
    pass


class ExecutionInfrastructureError(ExecutionError):
    pass


@dataclass(frozen=True, slots=True)
class ExecutionItemRecord:
    id: UUID
    ordinal: int
    test_case_id: UUID
    test_case_revision_id: UUID
    test_case_revision_version: int
    status: str
    verdict: str | None
    started_at: datetime | None
    finished_at: datetime | None
    attempts: tuple[AttemptRecord, ...] = ()
    attempt_count: int = 0
    attempts_truncated: bool = False
    baseline_activation_id: UUID | None = None
    baseline_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AttemptReadRecord:
    execution_id: UUID
    attempt: AttemptRecord
    artifact: ResponseArtifact | None
    read_at: datetime
    comparison: ComparisonRead | None = None
    evaluations: tuple[EvaluationRead, ...] = ()
    promotion: PromotionRead | None = None


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    id: UUID
    project_id: UUID
    environment_id: UUID
    environment_revision_id: UUID
    source_type: str
    source_id: UUID
    source_revision_id: UUID
    status: str
    verdict: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    items: tuple[ExecutionItemRecord, ...]
    pinned_change_events: tuple[ChangeEvent, ...] = ()
    change_evidence: ChangeRead = ChangeRead(())

    @property
    def completed_item_count(self) -> int:
        return sum(
            item.status in {"completed", "failed", "indeterminate", "skipped"}
            for item in self.items
        )


@dataclass(frozen=True, slots=True)
class ExecutionPageRecord:
    items: tuple[ExecutionRecord, ...]
    next_after: tuple[datetime, UUID] | None


@dataclass(frozen=True, slots=True)
class ExecutionCreateCommand:
    environment_id: UUID
    test_case_id: UUID | None = None
    suite_id: UUID | None = None


def hash_idempotency_key(value: str) -> str:
    return sha256(value.encode("ascii")).hexdigest()


def request_hash(command: ExecutionCreateCommand) -> str:
    payload = {
        "environment_id": str(command.environment_id),
        "suite_id": str(command.suite_id) if command.suite_id is not None else None,
        "test_case_id": str(command.test_case_id) if command.test_case_id is not None else None,
    }
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class PostgresExecutionService:
    """Atomic M3-01 execution creation and bounded read service."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        ids: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] | None = None,
        max_deliveries: int = 3,
    ) -> None:
        if not 1 <= max_deliveries <= 3:
            raise ValueError("max_deliveries must be between 1 and 3")
        self.sessions = sessions
        self.ids = ids
        self.clock = clock
        self.max_deliveries = max_deliveries

    def _now(self, session: Session) -> datetime:
        if self.clock is not None:
            return self.clock()
        value = session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("PostgreSQL clock unavailable")
        return value

    def create(
        self, command: ExecutionCreateCommand, *, idempotency_key: str | None = None
    ) -> ExecutionRecord:
        if (command.test_case_id is None) == (command.suite_id is None):
            raise ExecutionValidationError("exactly one execution source is required")
        key_hash = hash_idempotency_key(idempotency_key) if idempotency_key is not None else None
        canonical_hash = request_hash(command)
        try:
            with self.sessions.begin() as session:
                now = self._now(session)
                if key_hash is not None:
                    self._lock_idempotency_key(session, key_hash)
                    existing = session.scalar(
                        select(IdempotencyRecordRow)
                        .where(IdempotencyRecordRow.key_hash == key_hash)
                        .with_for_update()
                    )
                    if existing is not None:
                        if existing.expires_at > now:
                            if existing.request_hash != canonical_hash:
                                raise ExecutionIdempotencyConflict
                            record = self._record(session, existing.execution_id)
                            if record is None:
                                raise ExecutionInfrastructureError("idempotency_subject_missing")
                            return record
                        session.delete(existing)
                        session.flush()

                project_id, environment_revision_id, source_type, source_revision_id, item_refs = (
                    self._resolve_inputs(session, command)
                )
                execution_id = self.ids()
                session.add(
                    ExecutionRow(
                        id=execution_id,
                        project_id=project_id,
                        environment_id=command.environment_id,
                        environment_revision_id=environment_revision_id,
                        source_type=source_type,
                        source_id=command.test_case_id or command.suite_id,
                        source_revision_id=source_revision_id,
                        status="queued",
                        verdict=None,
                        result_contract_version=1,
                        created_at=now,
                    )
                )
                session.flush()
                for (
                    ordinal,
                    test_case_id,
                    revision_id,
                    revision_version,
                    baseline_activation_id,
                    baseline_id,
                ) in item_refs:
                    session.add(
                        ExecutionItemRow(
                            id=self.ids(),
                            execution_id=execution_id,
                            ordinal=ordinal,
                            project_id=project_id,
                            test_case_id=test_case_id,
                            test_case_revision_id=revision_id,
                            test_case_revision_version=revision_version,
                            status="pending",
                            verdict=None,
                            result_contract_version=1,
                            baseline_activation_id=baseline_activation_id,
                            baseline_id=baseline_id,
                            started_at=None,
                            finished_at=None,
                        )
                    )
                session.add(
                    JobRow(
                        id=self.ids(),
                        kind="execute_execution",
                        subject_id=execution_id,
                        state="pending",
                        available_at=now,
                        delivery_count=0,
                        max_deliveries=self.max_deliveries,
                        created_at=now,
                    )
                )
                if key_hash is not None:
                    session.add(
                        IdempotencyRecordRow(
                            key_hash=key_hash,
                            request_hash=canonical_hash,
                            execution_id=execution_id,
                            expires_at=now + timedelta(hours=24),
                            created_at=now,
                        )
                    )
                record = self._record(session, execution_id)
                if record is None:
                    raise ExecutionInfrastructureError("execution_materialization_missing")
                return record
        except (ExecutionError, OperationalError, IntegrityError):
            raise
        except Exception as error:
            raise ExecutionInfrastructureError("execution_creation_failed") from error

    @staticmethod
    def _lock_idempotency_key(session: Session, key_hash: str) -> None:
        lock_value = int.from_bytes(bytes.fromhex(key_hash[:16]), byteorder="big", signed=True)
        session.execute(select(func.pg_advisory_xact_lock(lock_value)))

    def _resolve_inputs(
        self, session: Session, command: ExecutionCreateCommand
    ) -> tuple[UUID, UUID, str, UUID, list[tuple[int, UUID, UUID, int, UUID | None, UUID | None]]]:
        environment = session.scalar(
            select(EnvironmentRow)
            .where(EnvironmentRow.id == command.environment_id)
            .with_for_update()
        )
        if environment is None:
            raise ExecutionResourceNotFound
        project = session.scalar(select(ProjectRow).where(ProjectRow.id == environment.project_id))
        if project is None or project.deleted_at is not None:
            raise ExecutionResourceNotFound
        environment_revision = session.scalar(
            select(EnvironmentRevisionRow).where(
                EnvironmentRevisionRow.id == environment.active_revision_id,
                EnvironmentRevisionRow.environment_id == environment.id,
            )
        )
        if environment_revision is None:
            raise ExecutionResourceNotFound

        if command.test_case_id is not None:
            test_case = session.scalar(
                select(TestCaseRow).where(TestCaseRow.id == command.test_case_id).with_for_update()
            )
            if test_case is None or test_case.project_id != environment.project_id:
                raise ExecutionResourceNotFound
            revision = session.scalar(
                select(TestCaseRevisionRow).where(
                    TestCaseRevisionRow.id == test_case.active_revision_id,
                    TestCaseRevisionRow.test_case_id == test_case.id,
                )
            )
            if revision is None:
                raise ExecutionResourceNotFound
            activation = session.scalar(
                select(BaselineActivationRow).where(
                    BaselineActivationRow.test_case_id == test_case.id,
                    BaselineActivationRow.environment_id == environment.id,
                    BaselineActivationRow.project_id == environment.project_id,
                    BaselineActivationRow.deactivated_at.is_(None),
                )
            )
            items = [
                (
                    0,
                    test_case.id,
                    revision.id,
                    revision.version,
                    activation.id if activation is not None else None,
                    activation.baseline_id if activation is not None else None,
                )
            ]
            return (
                environment.project_id,
                environment_revision.id,
                "test_case",
                revision.id,
                items,
            )

        assert command.suite_id is not None
        suite = session.scalar(
            select(SuiteRow).where(SuiteRow.id == command.suite_id).with_for_update()
        )
        if suite is None or suite.project_id != environment.project_id:
            raise ExecutionResourceNotFound
        suite_revision = session.scalar(
            select(SuiteRevisionRow).where(
                SuiteRevisionRow.id == suite.active_revision_id,
                SuiteRevisionRow.suite_id == suite.id,
                SuiteRevisionRow.project_id == suite.project_id,
            )
        )
        if suite_revision is None:
            raise ExecutionResourceNotFound
        item_rows = list(
            session.scalars(
                select(SuiteRevisionItemRow)
                .where(SuiteRevisionItemRow.suite_revision_id == suite_revision.id)
                .order_by(SuiteRevisionItemRow.ordinal)
            )
        )
        if not item_rows or len(item_rows) > 100:
            raise ExecutionResourceNotFound
        test_case_ids = sorted({row.test_case_id for row in item_rows})
        locked_test_cases = list(
            session.scalars(
                select(TestCaseRow)
                .where(TestCaseRow.id.in_(test_case_ids))
                .order_by(TestCaseRow.id)
                .with_for_update()
            )
        )
        if len(locked_test_cases) != len(test_case_ids):
            raise ExecutionResourceNotFound
        activations = {
            activation.test_case_id: activation
            for activation in session.scalars(
                select(BaselineActivationRow).where(
                    BaselineActivationRow.test_case_id.in_(test_case_ids),
                    BaselineActivationRow.environment_id == environment.id,
                    BaselineActivationRow.project_id == environment.project_id,
                    BaselineActivationRow.deactivated_at.is_(None),
                )
            )
        }
        items = [
            (
                row.ordinal,
                row.test_case_id,
                row.test_case_revision_id,
                row.test_case_revision_version,
                activations[row.test_case_id].id if row.test_case_id in activations else None,
                activations[row.test_case_id].baseline_id
                if row.test_case_id in activations
                else None,
            )
            for row in item_rows
        ]
        return (
            environment.project_id,
            environment_revision.id,
            "suite",
            suite_revision.id,
            items,
        )

    def get(self, execution_id: UUID) -> ExecutionRecord | None:
        with self.sessions() as session:
            return self._record(session, execution_id)

    def get_attempt(self, attempt_id: UUID) -> AttemptReadRecord | None:
        """Read one attempt and its already-redacted observation.

        The join keeps an attempt readable only when it belongs to a materialized,
        non-deleted project execution.  No request document or lease data is read.
        """
        with self.sessions() as session:
            row = session.scalar(
                select(TestAttemptRow)
                .join(ExecutionItemRow, ExecutionItemRow.id == TestAttemptRow.execution_item_id)
                .join(ExecutionRow, ExecutionRow.id == ExecutionItemRow.execution_id)
                .join(ProjectRow, ProjectRow.id == ExecutionRow.project_id)
                .where(
                    TestAttemptRow.id == attempt_id,
                    ExecutionRow.project_id.is_not(None),
                    ProjectRow.deleted_at.is_(None),
                )
            )
            if row is None:
                return None
            execution_id = session.scalar(
                select(ExecutionItemRow.execution_id).where(
                    ExecutionItemRow.id == row.execution_item_id
                )
            )
            if execution_id is None:
                return None
            item = session.get(ExecutionItemRow, row.execution_item_id)
            execution = session.get(ExecutionRow, execution_id)
            if item is None or execution is None or execution.project_id is None:
                return None
            artifact_row = session.get(ResponseArtifactRow, attempt_id)
            artifact = (
                ResponseArtifact(
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
                if artifact_row is not None
                else None
            )
            return AttemptReadRecord(
                execution_id=execution_id,
                attempt=PostgresAttemptStore._record(row),
                artifact=artifact,
                read_at=self._now(session),
                comparison=self._comparison(session, row),
                evaluations=self._evaluations(session, row.id),
                promotion=self._promotion(session, row, item, execution.environment_id),
            )

    def list(
        self,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None = None,
        project_id: UUID | None = None,
        environment_id: UUID | None = None,
        test_case_id: UUID | None = None,
        suite_id: UUID | None = None,
        status: str | None = None,
        verdict: str | None = None,
        created_from: datetime | None = None,
        created_before: datetime | None = None,
    ) -> ExecutionPageRecord:
        if not 1 <= limit <= 100:
            raise ExecutionValidationError("execution page limit is invalid")
        if test_case_id is not None and suite_id is not None:
            raise ExecutionValidationError("execution source filters conflict")
        with self.sessions() as session:
            if project_id is not None:
                project = session.scalar(select(ProjectRow).where(ProjectRow.id == project_id))
                if project is None or project.deleted_at is not None:
                    raise ExecutionResourceNotFound
            statement = (
                select(ExecutionRow)
                .join(ProjectRow, ProjectRow.id == ExecutionRow.project_id)
                .where(ExecutionRow.project_id.is_not(None), ProjectRow.deleted_at.is_(None))
            )
            if project_id is not None:
                statement = statement.where(ExecutionRow.project_id == project_id)
            if environment_id is not None:
                statement = statement.where(ExecutionRow.environment_id == environment_id)
            if test_case_id is not None:
                statement = statement.where(
                    ExecutionRow.source_type == "test_case", ExecutionRow.source_id == test_case_id
                )
            if suite_id is not None:
                statement = statement.where(
                    ExecutionRow.source_type == "suite", ExecutionRow.source_id == suite_id
                )
            if status is not None:
                statement = statement.where(ExecutionRow.status == status)
            if verdict is not None:
                statement = statement.where(ExecutionRow.verdict == verdict)
            if created_from is not None:
                statement = statement.where(ExecutionRow.created_at >= created_from)
            if created_before is not None:
                statement = statement.where(ExecutionRow.created_at < created_before)
            if after is not None:
                statement = statement.where(
                    or_(
                        ExecutionRow.created_at > after[0],
                        and_(ExecutionRow.created_at == after[0], ExecutionRow.id > after[1]),
                    )
                )
            rows = list(
                session.scalars(
                    statement.order_by(ExecutionRow.created_at, ExecutionRow.id).limit(limit + 1)
                )
            )
            has_more = len(rows) > limit
            records = tuple(
                self._record(session, row.id, include_attempts=False) for row in rows[:limit]
            )
            if any(record is None for record in records):
                raise ExecutionInfrastructureError("execution_read_failed")
            return ExecutionPageRecord(
                items=tuple(record for record in records if record is not None),
                next_after=(rows[limit - 1].created_at, rows[limit - 1].id) if has_more else None,
            )

    @staticmethod
    def _record(
        session: Session, execution_id: UUID, *, include_attempts: bool = True
    ) -> ExecutionRecord | None:
        execution = session.get(ExecutionRow, execution_id)
        if execution is None or execution.project_id is None:
            return None
        project = session.get(ProjectRow, execution.project_id)
        if project is None or project.deleted_at is not None:
            return None
        if (
            execution.environment_id is None
            or execution.environment_revision_id is None
            or execution.source_type is None
            or execution.source_id is None
            or execution.source_revision_id is None
        ):
            return None
        items: list[ExecutionItemRecord] = []
        for row in session.scalars(
            select(ExecutionItemRow)
            .where(ExecutionItemRow.execution_id == execution.id)
            .order_by(ExecutionItemRow.ordinal)
        ):
            attempt_records: tuple[AttemptRecord, ...] = ()
            attempt_count = 0
            attempts_truncated = False
            if include_attempts:
                attempt_count = int(
                    session.scalar(
                        select(func.count(TestAttemptRow.id)).where(
                            TestAttemptRow.execution_item_id == row.id
                        )
                    )
                    or 0
                )
                attempts_truncated = attempt_count > 100
                attempt_statement = select(TestAttemptRow).where(
                    TestAttemptRow.execution_item_id == row.id
                )
                if attempts_truncated:
                    attempt_statement = attempt_statement.order_by(
                        TestAttemptRow.sequence.desc(), TestAttemptRow.id.desc()
                    ).limit(100)
                    attempt_rows = list(session.scalars(attempt_statement))
                    attempt_rows.reverse()
                else:
                    attempt_rows = list(
                        session.scalars(
                            attempt_statement.order_by(
                                TestAttemptRow.sequence, TestAttemptRow.id
                            ).limit(100)
                        )
                    )
                attempt_records = tuple(
                    PostgresAttemptStore._record(attempt_row) for attempt_row in attempt_rows
                )
            items.append(
                ExecutionItemRecord(
                    id=row.id,
                    ordinal=row.ordinal,
                    test_case_id=row.test_case_id,
                    test_case_revision_id=row.test_case_revision_id,
                    test_case_revision_version=row.test_case_revision_version,
                    status=row.status,
                    verdict=row.verdict,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                    attempts=attempt_records,
                    attempt_count=attempt_count,
                    attempts_truncated=attempts_truncated,
                    baseline_activation_id=row.baseline_activation_id,
                    baseline_id=row.baseline_id,
                )
            )
        pinned, contextual = (
            PostgresExecutionService._change_reads(session, execution, items)
            if include_attempts
            else ((), ChangeRead(()))
        )
        return ExecutionRecord(
            id=execution.id,
            project_id=execution.project_id,
            environment_id=execution.environment_id,
            environment_revision_id=execution.environment_revision_id,
            source_type=execution.source_type,
            source_id=execution.source_id,
            source_revision_id=execution.source_revision_id,
            status=execution.status,
            verdict=execution.verdict,
            created_at=execution.created_at,
            started_at=execution.started_at,
            finished_at=execution.finished_at,
            items=tuple(items),
            pinned_change_events=pinned,
            change_evidence=contextual,
        )

    @staticmethod
    def _comparison(session: Session, attempt: TestAttemptRow) -> ComparisonRead:
        empty = {
            "baseline_activation_id": None,
            "baseline_id": None,
            "baseline_version": None,
            "policy_fingerprint": None,
            "checked_at": None,
        }
        if attempt.result_contract_version == 0 or attempt.evaluation_error_code is not None:
            return ComparisonRead(state="not_evaluated", **empty)
        row = session.get(BaselineComparisonRow, attempt.id)
        if row is not None:
            return ComparisonRead(
                state=row.state,
                baseline_activation_id=row.baseline_activation_id,
                baseline_id=row.baseline_id,
                baseline_version=row.baseline_version,
                policy_fingerprint=row.policy_fingerprint,
                checked_at=row.checked_at,
            )
        if attempt.state in {"prepared", "dispatching", "response_received"}:
            return ComparisonRead(state="pending", **empty)
        return ComparisonRead(state="not_evaluated", **empty)

    @staticmethod
    def _evaluations(session: Session, attempt_id: UUID) -> tuple[EvaluationRead, ...]:
        return tuple(
            EvaluationRead(
                id=row.id,
                ordinal=row.ordinal,
                kind=row.kind,
                rule_id=row.rule_id,
                severity=row.severity,
                outcome=row.outcome,
                message_code=row.message_code,
                expected=row.expected,
                actual=row.actual,
                evidence_omitted=row.evidence_omitted,
            )
            for row in session.scalars(
                select(EvaluationRow)
                .where(EvaluationRow.attempt_id == attempt_id)
                .order_by(EvaluationRow.ordinal)
            )
        )

    @staticmethod
    def _promotion(
        session: Session,
        attempt: TestAttemptRow,
        item: ExecutionItemRow,
        environment_id: UUID | None,
    ) -> PromotionRead:
        if attempt.result_contract_version == 0:
            return PromotionRead(False, (), ("attempt_not_evaluated",))
        if attempt.state != "evaluated":
            code = (
                "evaluation_inconclusive"
                if attempt.evaluation_error_code is not None
                else "attempt_not_evaluated"
            )
            return PromotionRead(False, (), (code,))
        if attempt.finished_at is None:
            return PromotionRead(False, (), ("attempt_not_evaluated",))
        if environment_id is None:
            return PromotionRead(False, (), ("attempt_not_evaluated",))
        from sentinel.persistence.regression import PostgresBaselineRepository
        from sentinel.regression.baselines import BaselineScope

        test_case = session.get(TestCaseRow, item.test_case_id)
        if test_case is None:
            return PromotionRead(False, (), ("attempt_not_evaluated",))
        revision = session.get(TestCaseRevisionRow, test_case.active_revision_id)
        if revision is None:
            return PromotionRead(False, (), ("attempt_not_evaluated",))
        assessment = PostgresBaselineRepository(session).get_source_assessment(
            BaselineScope(item.test_case_id, environment_id),
            attempt.id,
            current_policy_fingerprint=revision.policy_fingerprint,
        )
        if assessment is None:
            return PromotionRead(False, (), ("attempt_not_evaluated",))
        return PromotionRead(
            assessment.eligible,
            assessment.warning_codes,
            assessment.ineligibility_codes,
        )

    @staticmethod
    def _change_event(row: ChangeEventRow) -> ChangeEvent | None:
        try:
            fields = row.summary.get("changed_fields", [])
            if not isinstance(fields, list) or not all(isinstance(value, str) for value in fields):
                return None
            return ChangeEvent(
                id=row.id,
                project_id=row.project_id,
                kind=ChangeEventKind(row.kind),
                subject_type=ChangeSubjectType(row.subject_type),
                subject_id=row.subject_id,
                before_ref=row.before_ref,
                after_ref=row.after_ref,
                summary=ChangeSummary.from_values(fields),
                created_at=row.created_at,
            )
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _change_reads(
        session: Session, execution: ExecutionRow, items: Sequence[ExecutionItemRecord]
    ) -> tuple[tuple[ChangeEvent, ...], ChangeRead]:
        if execution.project_id is None:
            return (), ChangeRead(())
        anchor_conditions: list[Any] = [
            and_(
                ChangeEventRow.subject_type == "environment",
                ChangeEventRow.subject_id == execution.environment_id,
                ChangeEventRow.after_ref == execution.environment_revision_id,
                or_(
                    ChangeEventRow.before_ref.is_(None),
                    ChangeEventRow.before_ref != ChangeEventRow.after_ref,
                ),
            ),
            and_(
                ChangeEventRow.subject_type == execution.source_type,
                ChangeEventRow.subject_id == execution.source_id,
                ChangeEventRow.after_ref == execution.source_revision_id,
                or_(
                    ChangeEventRow.before_ref.is_(None),
                    ChangeEventRow.before_ref != ChangeEventRow.after_ref,
                ),
            ),
        ]
        for item in items:
            anchor_conditions.append(
                and_(
                    ChangeEventRow.subject_type == "test_case",
                    ChangeEventRow.subject_id == item.test_case_id,
                    ChangeEventRow.after_ref == item.test_case_revision_id,
                    or_(
                        ChangeEventRow.before_ref.is_(None),
                        ChangeEventRow.before_ref != ChangeEventRow.after_ref,
                    ),
                )
            )
            if item.baseline_id is not None and item.baseline_activation_id is not None:
                anchor_conditions.append(
                    and_(
                        ChangeEventRow.subject_type == "baseline",
                        ChangeEventRow.subject_id == item.baseline_id,
                        ChangeEventRow.after_ref == item.baseline_activation_id,
                    )
                )
        anchor_rows = session.scalars(
            select(ChangeEventRow)
            .where(
                ChangeEventRow.project_id == execution.project_id,
                or_(*cast(Any, anchor_conditions)),
            )
            .order_by(ChangeEventRow.created_at, ChangeEventRow.id)
        )
        pinned_by_id = {
            row.id: event
            for row in anchor_rows
            if (event := PostgresExecutionService._change_event(row)) is not None
        }

        baseline_finished: dict[UUID, datetime] = {}
        for item in items:
            if item.baseline_id is not None:
                baseline = session.get(BaselineRow, item.baseline_id)
                if baseline is not None:
                    baseline_finished[item.baseline_id] = baseline.source_finished_at
        contextual_conditions: list[Any] = [
            and_(
                ChangeEventRow.subject_type == "environment",
                ChangeEventRow.subject_id == execution.environment_id,
            ),
            and_(
                ChangeEventRow.subject_type == execution.source_type,
                ChangeEventRow.subject_id == execution.source_id,
            ),
        ]
        contextual_conditions.extend(
            and_(
                ChangeEventRow.subject_type == "test_case",
                ChangeEventRow.subject_id == item.test_case_id,
            )
            for item in items
        )
        contextual_conditions.extend(
            and_(
                ChangeEventRow.subject_type == "baseline", ChangeEventRow.subject_id == baseline_id
            )
            for baseline_id in baseline_finished
        )
        contextual_rows = list(
            session.scalars(
                select(ChangeEventRow)
                .where(
                    ChangeEventRow.project_id == execution.project_id,
                    ChangeEventRow.created_at <= execution.created_at,
                    ChangeEventRow.id.not_in(pinned_by_id),
                    or_(*cast(Any, contextual_conditions)),
                )
                .order_by(ChangeEventRow.created_at.desc(), ChangeEventRow.id.desc())
                .limit(129)
            )
        )
        item_thresholds = [
            (item, baseline_finished[item.baseline_id])
            for item in items
            if item.baseline_id is not None and item.baseline_id in baseline_finished
        ]
        contextual: list[ChangeEvent] = []
        for row in contextual_rows:
            relevant = any(
                row.created_at > threshold
                and (
                    row.subject_type == "environment"
                    and row.subject_id == execution.environment_id
                    or row.subject_type == execution.source_type
                    and row.subject_id == execution.source_id
                    or row.subject_type == "test_case"
                    and row.subject_id == item.test_case_id
                    or row.subject_type == "baseline"
                    and row.subject_id == item.baseline_id
                )
                for item, threshold in item_thresholds
            )
            if not relevant:
                continue
            event = PostgresExecutionService._change_event(row)
            if event is not None:
                contextual.append(event)
            if len(contextual) == 129:
                break
        truncated = len(contextual) > 128
        contextual = contextual[:128]
        contextual.reverse()
        return tuple(pinned_by_id.values()), ChangeRead(tuple(contextual), truncated)
