from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

import pytest

from sentinel.catalog.changes import ChangeEvent
from sentinel.catalog.projects import Project
from sentinel.catalog.suites import (
    Suite as DomainSuite,
)
from sentinel.catalog.suites import (
    SuiteReferenceNotFound,
    SuiteRevisionConflict,
    SuiteService,
    SuiteValidationError,
)
from sentinel.catalog.suites import (
    TestCaseRevisionReference as RevisionReference,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000002")
SUITE_ID = UUID("00000000-0000-4000-8000-000000000010")
SUITE_REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000011")
EVENT_1_ID = UUID("00000000-0000-4000-8000-000000000012")
SUITE_REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000013")
EVENT_2_ID = UUID("00000000-0000-4000-8000-000000000014")
NOW = datetime(2030, 1, 1, tzinfo=UTC)
CASE_1_ID = UUID("00000000-0000-4000-8000-000000000021")
CASE_2_ID = UUID("00000000-0000-4000-8000-000000000022")
REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000031")
REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000032")
REVISION_OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000033")


class Projects:
    def __init__(self) -> None:
        self.items = {
            PROJECT_ID: Project(PROJECT_ID, "Synthetic", NOW, None, 1),
            OTHER_PROJECT_ID: Project(OTHER_PROJECT_ID, "Other", NOW, None, 1),
        }

    def add(self, project: Project) -> None:
        self.items[project.id] = project

    def get(self, project_id: UUID) -> Project | None:
        return self.items.get(project_id)

    def list_after(
        self,
        *,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Project]:
        return list(self.items.values())[:limit]


class Suites:
    def __init__(self) -> None:
        self.items: dict[UUID, DomainSuite] = {}
        self.pins = {
            (PROJECT_ID, REVISION_1_ID): RevisionReference(CASE_1_ID, 4),
            (PROJECT_ID, REVISION_2_ID): RevisionReference(CASE_2_ID, 2),
            (OTHER_PROJECT_ID, REVISION_OTHER_PROJECT_ID): RevisionReference(CASE_1_ID, 9),
        }

    def add(self, suite: DomainSuite) -> None:
        self.items[suite.id] = suite

    def get(self, suite_id: UUID, *, for_update: bool = False) -> DomainSuite | None:
        return self.items.get(suite_id)

    def replace(self, suite: DomainSuite) -> None:
        self.items[suite.id] = suite

    def list_after(
        self,
        *,
        project_id: UUID,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[DomainSuite]:
        items = [suite for suite in self.items.values() if suite.project_id == project_id]
        return sorted(items, key=lambda suite: (suite.created_at, suite.id))[:limit]

    def get_test_case_revision_for_project(
        self, project_id: UUID, revision_id: UUID
    ) -> RevisionReference | None:
        return self.pins.get((project_id, revision_id))


class Changes:
    def __init__(self) -> None:
        self.items: list[ChangeEvent] = []

    def add(self, event: ChangeEvent) -> None:
        self.items.append(event)


class UnitOfWork:
    def __init__(self) -> None:
        self.projects = Projects()
        self.suites = Suites()
        self.changes = Changes()

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def commit(self) -> None:
        return None


def service(unit_of_work: UnitOfWork, ids: list[UUID]) -> SuiteService:
    values = iter(ids)
    return SuiteService(
        lambda: unit_of_work,
        ids=lambda: next(values),
        clock=lambda: NOW,
    )


def test_create_assigns_contiguous_ordinals_and_exact_revision_versions() -> None:
    unit_of_work = UnitOfWork()
    suite_service = service(
        unit_of_work,
        [SUITE_ID, SUITE_REVISION_1_ID, EVENT_1_ID],
    )

    created = suite_service.create(
        PROJECT_ID,
        name="Ordered checks",
        test_case_revision_ids=[REVISION_2_ID, REVISION_1_ID],
    )

    assert [
        (item.ordinal, item.test_case_id, item.test_case_revision_id)
        for item in created.active_revision.items
    ] == [
        (0, CASE_2_ID, REVISION_2_ID),
        (1, CASE_1_ID, REVISION_1_ID),
    ]
    assert [item.test_case_revision_version for item in created.active_revision.items] == [2, 4]
    assert unit_of_work.changes.items[0].kind.value == "suite_created"


@pytest.mark.parametrize(
    "revision_ids",
    [([], "empty"), ([REVISION_1_ID, REVISION_1_ID], "duplicate")],
)
def test_create_rejects_empty_or_duplicate_case_membership(
    revision_ids: tuple[list[UUID], str],
) -> None:
    unit_of_work = UnitOfWork()
    suite_service = service(unit_of_work, [SUITE_ID, SUITE_REVISION_1_ID, EVENT_1_ID])

    with pytest.raises(SuiteValidationError):
        suite_service.create(
            PROJECT_ID,
            name="Invalid suite",
            test_case_revision_ids=revision_ids[0],
        )

    assert unit_of_work.suites.items == {}
    assert unit_of_work.changes.items == []


def test_create_rejects_missing_or_cross_project_revision_without_writing() -> None:
    unit_of_work = UnitOfWork()
    suite_service = service(unit_of_work, [SUITE_ID, SUITE_REVISION_1_ID, EVENT_1_ID])

    with pytest.raises(SuiteReferenceNotFound):
        suite_service.create(
            PROJECT_ID,
            name="Foreign suite",
            test_case_revision_ids=[REVISION_OTHER_PROJECT_ID],
        )

    with pytest.raises(SuiteReferenceNotFound):
        suite_service.create(
            PROJECT_ID,
            name="Missing suite",
            test_case_revision_ids=[UUID("00000000-0000-4000-8000-000000000099")],
        )

    assert unit_of_work.suites.items == {}
    assert unit_of_work.changes.items == []


def test_update_creates_immutable_revision_and_rejects_stale_state() -> None:
    unit_of_work = UnitOfWork()
    suite_service = service(
        unit_of_work,
        [
            SUITE_ID,
            SUITE_REVISION_1_ID,
            EVENT_1_ID,
            SUITE_REVISION_2_ID,
            EVENT_2_ID,
        ],
    )
    created = suite_service.create(
        PROJECT_ID,
        name="Ordered checks",
        test_case_revision_ids=[REVISION_1_ID],
    )
    updated = suite_service.update(
        SUITE_ID,
        expected_state_version=1,
        name="Updated checks",
        test_case_revision_ids=[REVISION_2_ID],
    )

    assert created.active_revision.version == 1
    assert created.active_revision.items[0].test_case_revision_id == REVISION_1_ID
    assert updated.active_revision.version == 2
    assert updated.active_revision.items[0].test_case_revision_id == REVISION_2_ID
    assert len(unit_of_work.changes.items) == 2

    with pytest.raises(SuiteRevisionConflict):
        suite_service.update(
            SUITE_ID,
            expected_state_version=1,
            name="Stale",
            test_case_revision_ids=[REVISION_1_ID],
        )

    assert unit_of_work.suites.items[SUITE_ID].active_revision_id == SUITE_REVISION_2_ID
