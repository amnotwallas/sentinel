from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from sentinel.catalog.changes import (
    ChangeEvent,
    ChangeEventKind,
    ChangeSubjectType,
    ChangeSummary,
)
from sentinel.catalog.definitions import TestDefinition
from sentinel.catalog.ports import TestCaseUnitOfWorkFactory
from sentinel.catalog.projects import ProjectNotFound, normalize_project_name

UNSAFE_REPLAY_ACKNOWLEDGEMENT = "duplicate_effects_possible"


class TestCaseError(Exception):
    pass


class TestCaseValidationError(TestCaseError, ValueError):
    pass


class TestCaseNotFound(TestCaseError):
    pass


class TestCaseRevisionConflict(TestCaseError):
    pass


class TestCaseVersionExhausted(TestCaseError):
    pass


@dataclass(frozen=True, slots=True)
class TestCaseRevision:
    id: UUID
    test_case_id: UUID
    version: int
    definition: TestDefinition
    unsafe_replay_acknowledged_at: datetime | None
    unsafe_replay_acknowledgement: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TestCase:
    id: UUID
    project_id: UUID
    name: str
    active_revision_id: UUID
    active_revision: TestCaseRevision
    state_version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TestCasePage:
    items: list[TestCase]
    next_after: tuple[datetime, UUID] | None


@dataclass(frozen=True, slots=True)
class TestCaseRevisionPage:
    items: list[TestCaseRevision]
    next_after: tuple[int, UUID] | None


DocumentValidator = Callable[[object], TestDefinition]


def _consent(
    definition: TestDefinition, acknowledgement: str | None, *, now: datetime
) -> tuple[datetime | None, str | None]:
    allow_unsafe_replay = definition.document.get("allow_unsafe_replay")
    if allow_unsafe_replay is True:
        if acknowledgement != UNSAFE_REPLAY_ACKNOWLEDGEMENT:
            raise TestCaseValidationError("unsafe replay acknowledgement is required")
        return now, acknowledgement
    if acknowledgement is not None:
        raise TestCaseValidationError("unsafe replay acknowledgement is incompatible")
    return None, None


def _changed_fields(previous: TestDefinition, current: TestDefinition) -> list[str]:
    fields = ["request", "assertions", "comparison_policy", "redaction", "allow_unsafe_replay"]
    return [
        field for field in fields if previous.document.get(field) != current.document.get(field)
    ]


class TestCaseService:
    def __init__(
        self,
        unit_of_work: TestCaseUnitOfWorkFactory,
        *,
        ids: Callable[[], UUID],
        clock: Callable[[], datetime],
        validate_document: DocumentValidator,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ids = ids
        self._clock = clock
        self._validate_document = validate_document

    def create(
        self,
        project_id: UUID,
        *,
        name: str,
        definition: object,
        unsafe_replay_acknowledgement: str | None,
    ) -> TestCase:
        canonical_name = normalize_project_name(name)
        document = self._validate_document(definition)
        now = self._clock()
        acknowledged_at, acknowledgement = _consent(
            document, unsafe_replay_acknowledgement, now=now
        )
        test_case_id = self._ids()
        revision = TestCaseRevision(
            id=self._ids(),
            test_case_id=test_case_id,
            version=1,
            definition=document,
            unsafe_replay_acknowledged_at=acknowledged_at,
            unsafe_replay_acknowledgement=acknowledgement,
            created_at=now,
        )
        test_case = TestCase(
            id=test_case_id,
            project_id=project_id,
            name=canonical_name,
            active_revision_id=revision.id,
            active_revision=revision,
            state_version=1,
            created_at=now,
            updated_at=now,
        )
        with self._unit_of_work() as unit_of_work:
            project = unit_of_work.projects.get(project_id)
            if project is None or project.deleted_at is not None:
                raise ProjectNotFound
            unit_of_work.test_cases.add(test_case)
            unit_of_work.changes.add(
                ChangeEvent(
                    id=self._ids(),
                    project_id=project_id,
                    kind=ChangeEventKind.TEST_CASE_CREATED,
                    subject_type=ChangeSubjectType.TEST_CASE,
                    subject_id=test_case.id,
                    before_ref=None,
                    after_ref=revision.id,
                    summary=ChangeSummary.from_values(
                        [
                            "name",
                            "request",
                            "assertions",
                            "comparison_policy",
                            "redaction",
                            "allow_unsafe_replay",
                        ]
                    ),
                    created_at=now,
                )
            )
            unit_of_work.commit()
        return test_case

    def get(self, test_case_id: UUID) -> TestCase:
        with self._unit_of_work() as unit_of_work:
            test_case = unit_of_work.test_cases.get(test_case_id)
        if test_case is None:
            raise TestCaseNotFound
        return test_case

    def list(
        self,
        project_id: UUID,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> TestCasePage:
        if not 1 <= limit <= 100:
            raise TestCaseValidationError("test case page limit is invalid")
        with self._unit_of_work() as unit_of_work:
            project = unit_of_work.projects.get(project_id)
            if project is None or project.deleted_at is not None:
                raise ProjectNotFound
            test_cases = unit_of_work.test_cases.list_after(
                project_id=project_id, after=after, limit=limit + 1
            )
        has_more = len(test_cases) > limit
        items = test_cases[:limit]
        next_after = (items[-1].created_at, items[-1].id) if has_more and items else None
        return TestCasePage(items=items, next_after=next_after)

    def update(
        self,
        test_case_id: UUID,
        *,
        expected_state_version: int,
        name: str,
        definition: object,
        unsafe_replay_acknowledgement: str | None,
    ) -> TestCase:
        canonical_name = normalize_project_name(name)
        document = self._validate_document(definition)
        now = self._clock()
        acknowledged_at, acknowledgement = _consent(
            document, unsafe_replay_acknowledgement, now=now
        )
        with self._unit_of_work() as unit_of_work:
            current = unit_of_work.test_cases.get(test_case_id, for_update=True)
            if current is None:
                raise TestCaseNotFound
            if current.state_version != expected_state_version:
                raise TestCaseRevisionConflict
            if (
                current.state_version == 2_147_483_647
                or current.active_revision.version == 2_147_483_647
            ):
                raise TestCaseVersionExhausted
            revision = TestCaseRevision(
                id=self._ids(),
                test_case_id=current.id,
                version=current.active_revision.version + 1,
                definition=document,
                unsafe_replay_acknowledged_at=acknowledged_at,
                unsafe_replay_acknowledgement=acknowledgement,
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
            changed_fields = _changed_fields(current.active_revision.definition, document)
            if current.name != canonical_name:
                changed_fields.insert(0, "name")
            unit_of_work.test_cases.replace(updated)
            unit_of_work.changes.add(
                ChangeEvent(
                    id=self._ids(),
                    project_id=current.project_id,
                    kind=ChangeEventKind.TEST_CASE_REVISED,
                    subject_type=ChangeSubjectType.TEST_CASE,
                    subject_id=current.id,
                    before_ref=current.active_revision_id,
                    after_ref=revision.id,
                    summary=ChangeSummary.from_values(changed_fields),
                    created_at=now,
                )
            )
            unit_of_work.commit()
        return updated

    def revisions(
        self,
        test_case_id: UUID,
        *,
        limit: int,
        after: tuple[int, UUID] | None,
    ) -> TestCaseRevisionPage:
        if not 1 <= limit <= 100:
            raise TestCaseValidationError("test case revision page limit is invalid")
        with self._unit_of_work() as unit_of_work:
            if unit_of_work.test_cases.get(test_case_id) is None:
                raise TestCaseNotFound
            revisions = unit_of_work.test_cases.list_revisions_after(
                test_case_id=test_case_id, after=after, limit=limit + 1
            )
        has_more = len(revisions) > limit
        items = revisions[:limit]
        next_after = (items[-1].version, items[-1].id) if has_more and items else None
        return TestCaseRevisionPage(items=items, next_after=next_after)
