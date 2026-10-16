from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from sentinel.catalog.test_cases import TestCase, TestCaseRevision
from sentinel.persistence.models import TestCaseRevisionRow, TestCaseRow
from sentinel.security.definition_policy import validate_test_definition


class SqlAlchemyTestCaseRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, test_case: TestCase) -> None:
        self._session.add(
            TestCaseRow(
                id=test_case.id,
                project_id=test_case.project_id,
                name=test_case.name,
                active_revision_id=test_case.active_revision_id,
                state_version=test_case.state_version,
                created_at=test_case.created_at,
                updated_at=test_case.updated_at,
            )
        )
        self._session.flush()
        self._session.add(self._revision_row(test_case.active_revision))

    def get(self, test_case_id: UUID, *, for_update: bool = False) -> TestCase | None:
        statement = select(TestCaseRow).where(TestCaseRow.id == test_case_id)
        if for_update:
            statement = statement.with_for_update()
        row = self._session.scalar(statement)
        if row is None:
            return None
        revision = self._session.get(TestCaseRevisionRow, row.active_revision_id)
        if revision is None:
            raise RuntimeError("active test case revision is missing")
        return self._to_domain(row, revision)

    def replace(self, test_case: TestCase) -> None:
        row = self._session.get(TestCaseRow, test_case.id)
        if row is None:
            raise RuntimeError("test case is missing")
        if self._session.get(TestCaseRevisionRow, test_case.active_revision_id) is None:
            self._session.add(self._revision_row(test_case.active_revision))
        row.name = test_case.name
        row.active_revision_id = test_case.active_revision_id
        row.state_version = test_case.state_version
        row.updated_at = test_case.updated_at

    def list_after(
        self,
        *,
        project_id: UUID,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[TestCase]:
        statement = select(TestCaseRow).where(TestCaseRow.project_id == project_id)
        if after is not None:
            created_at, test_case_id = after
            statement = statement.where(
                or_(
                    TestCaseRow.created_at > created_at,
                    and_(
                        TestCaseRow.created_at == created_at,
                        TestCaseRow.id > test_case_id,
                    ),
                )
            )
        rows = self._session.scalars(
            statement.order_by(TestCaseRow.created_at, TestCaseRow.id).limit(limit)
        )
        return [self._from_row(row) for row in rows]

    def list_revisions_after(
        self,
        *,
        test_case_id: UUID,
        after: tuple[int, UUID] | None,
        limit: int,
    ) -> list[TestCaseRevision]:
        statement = select(TestCaseRevisionRow).where(
            TestCaseRevisionRow.test_case_id == test_case_id
        )
        if after is not None:
            version, revision_id = after
            statement = statement.where(
                or_(
                    TestCaseRevisionRow.version > version,
                    and_(
                        TestCaseRevisionRow.version == version,
                        TestCaseRevisionRow.id > revision_id,
                    ),
                )
            )
        rows = self._session.scalars(
            statement.order_by(TestCaseRevisionRow.version, TestCaseRevisionRow.id).limit(limit)
        )
        return [self._revision_to_domain(row) for row in rows]

    def _from_row(self, row: TestCaseRow) -> TestCase:
        revision = self._session.get(TestCaseRevisionRow, row.active_revision_id)
        if revision is None:
            raise RuntimeError("active test case revision is missing")
        return self._to_domain(row, revision)

    @staticmethod
    def _revision_row(revision: TestCaseRevision) -> TestCaseRevisionRow:
        return TestCaseRevisionRow(
            id=revision.id,
            test_case_id=revision.test_case_id,
            version=revision.version,
            definition=revision.definition.to_document(),
            policy_fingerprint=revision.definition.policy_fingerprint,
            unsafe_replay_acknowledged_at=revision.unsafe_replay_acknowledged_at,
            unsafe_replay_acknowledgement=revision.unsafe_replay_acknowledgement,
            created_at=revision.created_at,
        )

    @staticmethod
    def _revision_to_domain(row: TestCaseRevisionRow) -> TestCaseRevision:
        definition = validate_test_definition(row.definition)
        if definition.policy_fingerprint != row.policy_fingerprint:
            raise RuntimeError("test case policy fingerprint is inconsistent")
        return TestCaseRevision(
            id=row.id,
            test_case_id=row.test_case_id,
            version=row.version,
            definition=definition,
            unsafe_replay_acknowledged_at=row.unsafe_replay_acknowledged_at,
            unsafe_replay_acknowledgement=row.unsafe_replay_acknowledgement,
            created_at=row.created_at,
        )

    @classmethod
    def _to_domain(cls, row: TestCaseRow, revision: TestCaseRevisionRow) -> TestCase:
        return TestCase(
            id=row.id,
            project_id=row.project_id,
            name=row.name,
            active_revision_id=row.active_revision_id,
            active_revision=cls._revision_to_domain(revision),
            state_version=row.state_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
