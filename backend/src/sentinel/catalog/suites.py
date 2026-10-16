from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from sentinel.catalog.changes import (
    ChangeEvent,
    ChangeEventKind,
    ChangeSubjectType,
    ChangeSummary,
)
from sentinel.catalog.ports import SuiteUnitOfWork, SuiteUnitOfWorkFactory
from sentinel.catalog.projects import ProjectNotFound, normalize_project_name


class SuiteError(Exception):
    pass


class SuiteValidationError(SuiteError, ValueError):
    pass


class SuiteNotFound(SuiteError):
    pass


class SuiteReferenceNotFound(SuiteError):
    pass


class SuiteRevisionConflict(SuiteError):
    pass


class SuiteVersionExhausted(SuiteError):
    pass


@dataclass(frozen=True, slots=True)
class TestCaseRevisionReference:
    test_case_id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class SuiteRevisionItem:
    ordinal: int
    test_case_id: UUID
    test_case_revision_id: UUID
    test_case_revision_version: int


@dataclass(frozen=True, slots=True)
class SuiteRevision:
    id: UUID
    suite_id: UUID
    version: int
    items: list[SuiteRevisionItem]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Suite:
    id: UUID
    project_id: UUID
    name: str
    active_revision_id: UUID
    active_revision: SuiteRevision
    state_version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SuitePage:
    items: list[Suite]
    next_after: tuple[datetime, UUID] | None


class SuiteService:
    def __init__(
        self,
        unit_of_work: SuiteUnitOfWorkFactory,
        *,
        ids: Callable[[], UUID],
        clock: Callable[[], datetime],
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ids = ids
        self._clock = clock

    @staticmethod
    def _items(
        unit_of_work: SuiteUnitOfWork,
        project_id: UUID,
        revision_ids: Sequence[UUID],
    ) -> list[SuiteRevisionItem]:
        if not 1 <= len(revision_ids) <= 100:
            raise SuiteValidationError("suite must contain between one and one hundred items")
        suites = unit_of_work.suites
        items: list[SuiteRevisionItem] = []
        seen_test_cases: set[UUID] = set()
        for ordinal, revision_id in enumerate(revision_ids):
            reference = suites.get_test_case_revision_for_project(project_id, revision_id)
            if reference is None:
                raise SuiteReferenceNotFound
            if reference.test_case_id in seen_test_cases:
                raise SuiteValidationError("a test case may appear only once in a suite")
            seen_test_cases.add(reference.test_case_id)
            items.append(
                SuiteRevisionItem(
                    ordinal=ordinal,
                    test_case_id=reference.test_case_id,
                    test_case_revision_id=revision_id,
                    test_case_revision_version=reference.version,
                )
            )
        return items

    def create(
        self,
        project_id: UUID,
        *,
        name: str,
        test_case_revision_ids: Sequence[UUID],
    ) -> Suite:
        canonical_name = normalize_project_name(name)
        now = self._clock()
        suite_id = self._ids()
        with self._unit_of_work() as unit_of_work:
            project = unit_of_work.projects.get(project_id)
            if project is None or project.deleted_at is not None:
                raise ProjectNotFound
            items = self._items(unit_of_work, project_id, test_case_revision_ids)
            revision = SuiteRevision(
                id=self._ids(),
                suite_id=suite_id,
                version=1,
                items=items,
                created_at=now,
            )
            suite = Suite(
                id=suite_id,
                project_id=project_id,
                name=canonical_name,
                active_revision_id=revision.id,
                active_revision=revision,
                state_version=1,
                created_at=now,
                updated_at=now,
            )
            unit_of_work.suites.add(suite)
            unit_of_work.changes.add(
                ChangeEvent(
                    id=self._ids(),
                    project_id=project_id,
                    kind=ChangeEventKind.SUITE_CREATED,
                    subject_type=ChangeSubjectType.SUITE,
                    subject_id=suite.id,
                    before_ref=None,
                    after_ref=revision.id,
                    summary=ChangeSummary.from_values(["name", "suite_items"]),
                    created_at=now,
                )
            )
            unit_of_work.commit()
        return suite

    def get(self, suite_id: UUID) -> Suite:
        with self._unit_of_work() as unit_of_work:
            suite = unit_of_work.suites.get(suite_id)
        if suite is None:
            raise SuiteNotFound
        return suite

    def list(
        self,
        project_id: UUID,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> SuitePage:
        if not 1 <= limit <= 100:
            raise SuiteValidationError("suite page limit is invalid")
        with self._unit_of_work() as unit_of_work:
            project = unit_of_work.projects.get(project_id)
            if project is None or project.deleted_at is not None:
                raise ProjectNotFound
            suites = unit_of_work.suites.list_after(
                project_id=project_id, after=after, limit=limit + 1
            )
        has_more = len(suites) > limit
        items = suites[:limit]
        next_after = (items[-1].created_at, items[-1].id) if has_more and items else None
        return SuitePage(items=items, next_after=next_after)

    def update(
        self,
        suite_id: UUID,
        *,
        expected_state_version: int,
        name: str,
        test_case_revision_ids: Sequence[UUID],
    ) -> Suite:
        canonical_name = normalize_project_name(name)
        now = self._clock()
        with self._unit_of_work() as unit_of_work:
            current = unit_of_work.suites.get(suite_id, for_update=True)
            if current is None:
                raise SuiteNotFound
            if current.state_version != expected_state_version:
                raise SuiteRevisionConflict
            if (
                current.state_version == 2_147_483_647
                or current.active_revision.version == 2_147_483_647
            ):
                raise SuiteVersionExhausted
            items = self._items(unit_of_work, current.project_id, test_case_revision_ids)
            revision = SuiteRevision(
                id=self._ids(),
                suite_id=current.id,
                version=current.active_revision.version + 1,
                items=items,
                created_at=now,
            )
            updated = replace(
                current,
                name=canonical_name,
                active_revision_id=revision.id,
                active_revision=revision,
                state_version=current.state_version + 1,
                updated_at=now,
            )
            changed_fields: list[str] = []
            if current.name != canonical_name:
                changed_fields.append("name")
            if current.active_revision.items != items:
                changed_fields.append("suite_items")
            unit_of_work.suites.replace(updated)
            unit_of_work.changes.add(
                ChangeEvent(
                    id=self._ids(),
                    project_id=current.project_id,
                    kind=ChangeEventKind.SUITE_REVISED,
                    subject_type=ChangeSubjectType.SUITE,
                    subject_id=current.id,
                    before_ref=current.active_revision_id,
                    after_ref=revision.id,
                    summary=ChangeSummary.from_values(changed_fields),
                    created_at=now,
                )
            )
            unit_of_work.commit()
        return updated
