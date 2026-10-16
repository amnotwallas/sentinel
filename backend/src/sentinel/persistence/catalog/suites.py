from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from sentinel.catalog.suites import (
    Suite,
    SuiteRevision,
    SuiteRevisionItem,
    TestCaseRevisionReference,
)
from sentinel.persistence.models import (
    SuiteRevisionItemRow,
    SuiteRevisionRow,
    SuiteRow,
    TestCaseRevisionRow,
    TestCaseRow,
)


class SqlAlchemySuiteRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, suite: Suite) -> None:
        self._session.add(
            SuiteRow(
                id=suite.id,
                project_id=suite.project_id,
                name=suite.name,
                active_revision_id=suite.active_revision_id,
                state_version=suite.state_version,
                created_at=suite.created_at,
                updated_at=suite.updated_at,
            )
        )
        self._session.flush()
        self._add_revision(suite.active_revision, suite.project_id)

    def get(self, suite_id: UUID, *, for_update: bool = False) -> Suite | None:
        statement = select(SuiteRow).where(SuiteRow.id == suite_id)
        if for_update:
            statement = statement.with_for_update()
        row = self._session.scalar(statement)
        if row is None:
            return None
        revision = self._revision(row.active_revision_id)
        return self._to_domain(row, revision)

    def replace(self, suite: Suite) -> None:
        row = self._session.get(SuiteRow, suite.id)
        if row is None:
            raise RuntimeError("suite is missing")
        if self._session.get(SuiteRevisionRow, suite.active_revision_id) is None:
            self._add_revision(suite.active_revision, suite.project_id)
        row.name = suite.name
        row.active_revision_id = suite.active_revision_id
        row.state_version = suite.state_version
        row.updated_at = suite.updated_at

    def list_after(
        self,
        *,
        project_id: UUID,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Suite]:
        statement = select(SuiteRow).where(SuiteRow.project_id == project_id)
        if after is not None:
            created_at, suite_id = after
            statement = statement.where(
                or_(
                    SuiteRow.created_at > created_at,
                    and_(SuiteRow.created_at == created_at, SuiteRow.id > suite_id),
                )
            )
        rows = self._session.scalars(
            statement.order_by(SuiteRow.created_at, SuiteRow.id).limit(limit)
        )
        return [self._to_domain(row, self._revision(row.active_revision_id)) for row in rows]

    def get_test_case_revision_for_project(
        self, project_id: UUID, revision_id: UUID
    ) -> TestCaseRevisionReference | None:
        statement = (
            select(TestCaseRevisionRow.test_case_id, TestCaseRevisionRow.version)
            .join(TestCaseRow, TestCaseRow.id == TestCaseRevisionRow.test_case_id)
            .where(
                TestCaseRow.project_id == project_id,
                TestCaseRevisionRow.id == revision_id,
            )
        )
        result = self._session.execute(statement).one_or_none()
        if result is None:
            return None
        test_case_id, version = result
        return TestCaseRevisionReference(test_case_id=test_case_id, version=version)

    def _add_revision(self, revision: SuiteRevision, project_id: UUID) -> None:
        self._session.add(
            SuiteRevisionRow(
                id=revision.id,
                suite_id=revision.suite_id,
                project_id=project_id,
                version=revision.version,
                created_at=revision.created_at,
            )
        )
        self._session.flush()
        self._session.add_all(
            [
                SuiteRevisionItemRow(
                    suite_revision_id=revision.id,
                    ordinal=item.ordinal,
                    project_id=project_id,
                    test_case_id=item.test_case_id,
                    test_case_revision_id=item.test_case_revision_id,
                    test_case_revision_version=item.test_case_revision_version,
                )
                for item in revision.items
            ]
        )

    def _revision(self, revision_id: UUID) -> SuiteRevision:
        row = self._session.get(SuiteRevisionRow, revision_id)
        if row is None:
            raise RuntimeError("active suite revision is missing")
        item_rows = self._session.scalars(
            select(SuiteRevisionItemRow)
            .where(SuiteRevisionItemRow.suite_revision_id == row.id)
            .order_by(SuiteRevisionItemRow.ordinal)
        )
        return SuiteRevision(
            id=row.id,
            suite_id=row.suite_id,
            version=row.version,
            items=[
                SuiteRevisionItem(
                    ordinal=item.ordinal,
                    test_case_id=item.test_case_id,
                    test_case_revision_id=item.test_case_revision_id,
                    test_case_revision_version=item.test_case_revision_version,
                )
                for item in item_rows
            ],
            created_at=row.created_at,
        )

    def _to_domain(self, row: SuiteRow, revision: SuiteRevision) -> Suite:
        return Suite(
            id=row.id,
            project_id=row.project_id,
            name=row.name,
            active_revision_id=row.active_revision_id,
            active_revision=revision,
            state_version=row.state_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
