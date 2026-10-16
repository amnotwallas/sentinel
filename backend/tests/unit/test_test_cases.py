from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from sentinel.catalog.changes import ChangeEvent
from sentinel.catalog.projects import Project
from sentinel.catalog.test_cases import (
    TestCase as DomainTestCase,
)
from sentinel.catalog.test_cases import TestCaseRevision as DomainTestCaseRevision
from sentinel.catalog.test_cases import (
    TestCaseRevisionConflict as RevisionConflict,
)
from sentinel.catalog.test_cases import (
    TestCaseService as Service,
)
from sentinel.catalog.test_cases import TestCaseVersionExhausted as VersionExhausted
from sentinel.security.definition_policy import validate_test_definition

if TYPE_CHECKING:
    from sentinel.catalog.ports import TestCaseUnitOfWork as TestCaseUoW

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
TEST_CASE_ID = UUID("00000000-0000-4000-8000-000000000010")
REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000011")
EVENT_1_ID = UUID("00000000-0000-4000-8000-000000000012")
REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000013")
EVENT_2_ID = UUID("00000000-0000-4000-8000-000000000014")
NOW = datetime(2030, 1, 1, tzinfo=UTC)


class Projects:
    def add(self, project: Project) -> None:
        return None

    def get(self, project_id: UUID) -> Project | None:
        if project_id != PROJECT_ID:
            return None
        return Project(PROJECT_ID, "Synthetic", NOW, None, 1)

    def list_after(
        self,
        *,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Project]:
        return []


class MemoryTestCases:
    def __init__(self) -> None:
        self.items: dict[UUID, DomainTestCase] = {}

    def add(self, test_case: DomainTestCase) -> None:
        self.items[test_case.id] = test_case

    def get(self, test_case_id: UUID, *, for_update: bool = False) -> DomainTestCase | None:
        return self.items.get(test_case_id)

    def replace(self, test_case: DomainTestCase) -> None:
        self.items[test_case.id] = test_case

    def list_after(
        self,
        *,
        project_id: UUID,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[DomainTestCase]:
        return list(self.items.values())[:limit]

    def list_revisions_after(
        self,
        *,
        test_case_id: UUID,
        after: tuple[int, UUID] | None,
        limit: int,
    ) -> list[DomainTestCaseRevision]:
        test_case = self.items[test_case_id]
        return [test_case.active_revision][:limit]


class Changes:
    def add(self, event: ChangeEvent) -> None:
        return None


class UnitOfWork:
    def __init__(self) -> None:
        self.projects = Projects()
        self.test_cases = MemoryTestCases()
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


def definition(*, unsafe: bool = False) -> dict[str, object]:
    return {
        "request": {"method": "GET", "path": "/health"},
        "allow_unsafe_replay": unsafe,
    }


def test_service_creates_revision_and_requires_acknowledgement() -> None:
    unit_of_work = UnitOfWork()
    ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID])

    def factory() -> TestCaseUoW:
        return unit_of_work

    service = Service(
        factory,
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    )

    with pytest.raises(ValueError, match="acknowledgement"):
        service.create(
            PROJECT_ID,
            name="Probe",
            definition=definition(unsafe=True),
            unsafe_replay_acknowledgement=None,
        )


def test_service_rejects_stale_revision_without_new_history() -> None:
    unit_of_work = UnitOfWork()
    ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID, REVISION_2_ID, EVENT_2_ID])

    def factory() -> TestCaseUoW:
        return unit_of_work

    service = Service(
        factory,
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    )
    service.create(
        PROJECT_ID,
        name="Probe",
        definition=definition(),
        unsafe_replay_acknowledgement=None,
    )

    with pytest.raises(RevisionConflict):
        service.update(
            TEST_CASE_ID,
            expected_state_version=0,
            name="Stale",
            definition=definition(),
            unsafe_replay_acknowledgement=None,
        )


def test_service_rejects_revision_version_exhaustion_before_writing() -> None:
    unit_of_work = UnitOfWork()
    ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID])
    service = Service(
        lambda: unit_of_work,
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    )
    created = service.create(
        PROJECT_ID,
        name="Probe",
        definition=definition(),
        unsafe_replay_acknowledgement=None,
    )
    exhausted_revision = replace(created.active_revision, version=2_147_483_647)
    unit_of_work.test_cases.items[TEST_CASE_ID] = replace(
        created,
        active_revision=exhausted_revision,
        state_version=2_147_483_647,
    )

    with pytest.raises(VersionExhausted):
        service.update(
            TEST_CASE_ID,
            expected_state_version=2_147_483_647,
            name="Probe",
            definition=definition(),
            unsafe_replay_acknowledgement=None,
        )
