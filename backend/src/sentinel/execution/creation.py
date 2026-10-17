from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.persistence.models import (
    EnvironmentRevisionRow,
    EnvironmentRow,
    ExecutionItemRow,
    ExecutionRow,
    IdempotencyRecordRow,
    JobRow,
    ProjectRow,
    SuiteRevisionItemRow,
    SuiteRevisionRow,
    SuiteRow,
    TestCaseRevisionRow,
    TestCaseRow,
)
from sentinel.regression.policy import canonical_json


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
                        created_at=now,
                    )
                )
                session.flush()
                for ordinal, test_case_id, revision_id, revision_version in item_refs:
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
    ) -> tuple[UUID, UUID, str, UUID, list[tuple[int, UUID, UUID, int]]]:
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
            items = [(0, test_case.id, revision.id, revision.version)]
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
        items = [
            (
                row.ordinal,
                row.test_case_id,
                row.test_case_revision_id,
                row.test_case_revision_version,
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
            records = tuple(self._record(session, row.id) for row in rows[:limit])
            if any(record is None for record in records):
                raise ExecutionInfrastructureError("execution_read_failed")
            return ExecutionPageRecord(
                items=tuple(record for record in records if record is not None),
                next_after=(rows[limit - 1].created_at, rows[limit - 1].id) if has_more else None,
            )

    @staticmethod
    def _record(session: Session, execution_id: UUID) -> ExecutionRecord | None:
        execution = session.get(ExecutionRow, execution_id)
        if execution is None or execution.project_id is None:
            return None
        if (
            execution.environment_id is None
            or execution.environment_revision_id is None
            or execution.source_type is None
            or execution.source_id is None
            or execution.source_revision_id is None
        ):
            return None
        items = tuple(
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
            )
            for row in session.scalars(
                select(ExecutionItemRow)
                .where(ExecutionItemRow.execution_id == execution.id)
                .order_by(ExecutionItemRow.ordinal)
            )
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
            items=items,
        )
