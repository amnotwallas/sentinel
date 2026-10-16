from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.catalog.changes import ChangeEvent
from sentinel.catalog.suites import (
    SuiteReferenceNotFound,
    SuiteRevisionConflict,
    SuiteService,
)
from sentinel.catalog.test_cases import TestCaseService as CaseService
from sentinel.persistence.catalog.changes import SqlAlchemyChangeRepository
from sentinel.persistence.catalog.unit_of_work import PostgresCatalogUnitOfWork
from sentinel.persistence.models import (
    ChangeEventRow,
    SuiteRevisionItemRow,
    SuiteRevisionRow,
    SuiteRow,
)
from sentinel.security.definition_policy import validate_test_definition

pytestmark = pytest.mark.integration

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000101")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000102")
TEST_CASE_1_ID = UUID("00000000-0000-4000-8000-000000000111")
TEST_CASE_2_ID = UUID("00000000-0000-4000-8000-000000000112")
TEST_CASE_1_REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000121")
TEST_CASE_1_REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000122")
TEST_CASE_2_REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000123")
OTHER_TEST_CASE_ID = UUID("00000000-0000-4000-8000-000000000131")
OTHER_REVISION_ID = UUID("00000000-0000-4000-8000-000000000132")
SUITE_ID = UUID("00000000-0000-4000-8000-000000000141")
SUITE_REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000142")
SUITE_EVENT_1_ID = UUID("00000000-0000-4000-8000-000000000143")
SUITE_REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000144")
SUITE_EVENT_2_ID = UUID("00000000-0000-4000-8000-000000000145")
OTHER_SUITE_ID = UUID("00000000-0000-4000-8000-000000000146")
OTHER_SUITE_REVISION_ID = UUID("00000000-0000-4000-8000-000000000147")
OTHER_SUITE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000148")
NOW = datetime(2030, 1, 1, tzinfo=UTC)


def definition(path: str) -> dict[str, object]:
    return {
        "request": {"method": "GET", "path": path},
        "assertions": [],
        "comparison_policy": {},
        "redaction": {},
        "allow_unsafe_replay": False,
    }


def make_project(factory: sessionmaker[Session], project_id: UUID) -> None:
    from sentinel.catalog.projects import ProjectService

    ProjectService(
        lambda: PostgresCatalogUnitOfWork(factory), ids=lambda: project_id, clock=lambda: NOW
    ).create(f"Project {project_id.int}")


def make_test_case(
    factory: sessionmaker[Session],
    *,
    project_id: UUID,
    test_case_id: UUID,
    revision_id: UUID,
    event_id: UUID,
    path: str,
) -> None:
    ids = iter([test_case_id, revision_id, event_id])
    CaseService(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    ).create(
        project_id,
        name=f"Case {test_case_id.int}",
        definition=definition(path),
        unsafe_replay_acknowledgement=None,
    )


class FailingChanges(SqlAlchemyChangeRepository):
    def add(self, event: ChangeEvent) -> None:
        raise RuntimeError("synthetic change-event failure")


class FailingChangeUnitOfWork(PostgresCatalogUnitOfWork):
    def __enter__(self) -> "FailingChangeUnitOfWork":
        super().__enter__()
        assert self._session is not None
        self.changes = FailingChanges(self._session)
        return self


def make_suite_service(
    factory: sessionmaker[Session], ids: list[UUID], *, failing: bool = False
) -> SuiteService:
    values = iter(ids)
    uow = FailingChangeUnitOfWork if failing else PostgresCatalogUnitOfWork
    return SuiteService(
        lambda: uow(factory),
        ids=lambda: next(values),
        clock=lambda: NOW,
    )


def test_suite_pins_exact_revision_and_survives_later_test_case_update(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_1_ID,
        revision_id=TEST_CASE_1_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000151"),
        path="/v1",
    )
    suite = make_suite_service(factory, [SUITE_ID, SUITE_REVISION_1_ID, SUITE_EVENT_1_ID]).create(
        PROJECT_ID,
        name="Ordered suite",
        test_case_revision_ids=[TEST_CASE_1_REVISION_1_ID],
    )
    test_case_ids = iter([TEST_CASE_1_REVISION_2_ID, UUID("00000000-0000-4000-8000-000000000152")])
    CaseService(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(test_case_ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    ).update(
        TEST_CASE_1_ID,
        expected_state_version=1,
        name="Updated case",
        definition=definition("/v2"),
        unsafe_replay_acknowledgement=None,
    )

    loaded = make_suite_service(factory, []).get(SUITE_ID)

    assert suite.active_revision.items[0].test_case_revision_id == TEST_CASE_1_REVISION_1_ID
    assert suite.active_revision.items[0].test_case_revision_version == 1
    assert loaded.active_revision.items == suite.active_revision.items


def test_suite_rejects_missing_and_cross_project_revisions_atomically(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    make_project(factory, OTHER_PROJECT_ID)
    make_test_case(
        factory,
        project_id=OTHER_PROJECT_ID,
        test_case_id=OTHER_TEST_CASE_ID,
        revision_id=OTHER_REVISION_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000161"),
        path="/other",
    )
    service = make_suite_service(factory, [SUITE_ID, SUITE_REVISION_1_ID, SUITE_EVENT_1_ID])

    for revision_id in (OTHER_REVISION_ID, UUID("00000000-0000-4000-8000-000000000199")):
        with pytest.raises(SuiteReferenceNotFound):
            service.create(
                PROJECT_ID,
                name="Rejected suite",
                test_case_revision_ids=[revision_id],
            )

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SuiteRow)) == 0
        assert session.scalar(select(func.count()).select_from(SuiteRevisionRow)) == 0


def test_suite_update_rolls_back_identity_revision_items_and_event_on_failure(
    engine: Engine,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_1_ID,
        revision_id=TEST_CASE_1_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000171"),
        path="/v1",
    )
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_2_ID,
        revision_id=TEST_CASE_2_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000172"),
        path="/v2",
    )
    make_suite_service(factory, [SUITE_ID, SUITE_REVISION_1_ID, SUITE_EVENT_1_ID]).create(
        PROJECT_ID,
        name="Rollback suite",
        test_case_revision_ids=[TEST_CASE_1_REVISION_1_ID],
    )
    failing = make_suite_service(
        factory,
        [SUITE_REVISION_2_ID, SUITE_EVENT_2_ID],
        failing=True,
    )

    with pytest.raises(RuntimeError, match="synthetic change-event failure"):
        failing.update(
            SUITE_ID,
            expected_state_version=1,
            name="Changed",
            test_case_revision_ids=[TEST_CASE_2_REVISION_1_ID],
        )

    with Session(engine) as session:
        row = session.get(SuiteRow, SUITE_ID)
        assert row is not None
        assert row.active_revision_id == SUITE_REVISION_1_ID
        assert row.state_version == 1
        assert session.scalar(select(func.count()).select_from(SuiteRevisionRow)) == 1
        assert session.scalar(select(func.count()).select_from(SuiteRevisionItemRow)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEventRow)) == 3


def test_suite_create_rolls_back_identity_revision_items_and_event_on_failure(
    engine: Engine,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_1_ID,
        revision_id=TEST_CASE_1_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000176"),
        path="/v1",
    )
    failing = make_suite_service(
        factory,
        [SUITE_ID, SUITE_REVISION_1_ID, SUITE_EVENT_1_ID],
        failing=True,
    )

    with pytest.raises(RuntimeError, match="synthetic change-event failure"):
        failing.create(
            PROJECT_ID,
            name="Rejected suite",
            test_case_revision_ids=[TEST_CASE_1_REVISION_1_ID],
        )

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SuiteRow)) == 0
        assert session.scalar(select(func.count()).select_from(SuiteRevisionRow)) == 0
        assert session.scalar(select(func.count()).select_from(SuiteRevisionItemRow)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeEventRow)) == 1


def test_concurrent_same_etag_suite_updates_have_one_success_and_one_conflict(
    engine: Engine,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_1_ID,
        revision_id=TEST_CASE_1_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000181"),
        path="/v1",
    )
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_2_ID,
        revision_id=TEST_CASE_2_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000182"),
        path="/v2",
    )
    make_suite_service(factory, [SUITE_ID, SUITE_REVISION_1_ID, SUITE_EVENT_1_ID]).create(
        PROJECT_ID,
        name="Concurrent suite",
        test_case_revision_ids=[TEST_CASE_1_REVISION_1_ID],
    )

    def update_suite(revision_id: UUID, event_id: UUID) -> str:
        service = make_suite_service(factory, [revision_id, event_id])
        try:
            service.update(
                SUITE_ID,
                expected_state_version=1,
                name="Concurrent",
                test_case_revision_ids=[TEST_CASE_2_REVISION_1_ID],
            )
        except SuiteRevisionConflict:
            return "conflict"
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                update_suite,
                (SUITE_REVISION_2_ID, UUID("00000000-0000-4000-8000-000000000183")),
                (
                    UUID("00000000-0000-4000-8000-000000000184"),
                    UUID("00000000-0000-4000-8000-000000000185"),
                ),
            )
        )

    assert sorted(outcomes) == ["conflict", "success"]
    with Session(engine) as session:
        row = session.get(SuiteRow, SUITE_ID)
        assert row is not None
        assert row.state_version == 2
        assert row.active_revision_id in {
            SUITE_REVISION_2_ID,
            UUID("00000000-0000-4000-8000-000000000184"),
        }
        assert session.scalar(select(func.count()).select_from(SuiteRevisionRow)) == 2
        assert session.scalar(select(func.count()).select_from(SuiteRevisionItemRow)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(ChangeEventRow)
                .where(ChangeEventRow.kind == "suite_revised")
            )
            == 1
        )


def test_database_rejects_suite_item_revision_from_another_test_case(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_1_ID,
        revision_id=TEST_CASE_1_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000191"),
        path="/v1",
    )
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_2_ID,
        revision_id=TEST_CASE_2_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000192"),
        path="/v2",
    )
    make_suite_service(factory, [SUITE_ID, SUITE_REVISION_1_ID, SUITE_EVENT_1_ID]).create(
        PROJECT_ID,
        name="Constraint suite",
        test_case_revision_ids=[TEST_CASE_1_REVISION_1_ID],
    )

    with Session(engine) as session, pytest.raises(IntegrityError):
        session.add(
            SuiteRevisionItemRow(
                suite_revision_id=SUITE_REVISION_1_ID,
                ordinal=1,
                project_id=PROJECT_ID,
                test_case_id=TEST_CASE_2_ID,
                test_case_revision_id=TEST_CASE_1_REVISION_1_ID,
                test_case_revision_version=1,
            )
        )
        session.commit()


def test_database_rejects_cross_project_suite_item(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    make_project(factory, OTHER_PROJECT_ID)
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_1_ID,
        revision_id=TEST_CASE_1_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000193"),
        path="/v1",
    )
    make_test_case(
        factory,
        project_id=OTHER_PROJECT_ID,
        test_case_id=OTHER_TEST_CASE_ID,
        revision_id=OTHER_REVISION_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000194"),
        path="/other",
    )
    make_suite_service(factory, [SUITE_ID, SUITE_REVISION_1_ID, SUITE_EVENT_1_ID]).create(
        PROJECT_ID,
        name="Constraint suite",
        test_case_revision_ids=[TEST_CASE_1_REVISION_1_ID],
    )

    with Session(engine) as session, pytest.raises(IntegrityError):
        session.add(
            SuiteRevisionItemRow(
                suite_revision_id=SUITE_REVISION_1_ID,
                ordinal=1,
                project_id=PROJECT_ID,
                test_case_id=OTHER_TEST_CASE_ID,
                test_case_revision_id=OTHER_REVISION_ID,
                test_case_revision_version=1,
            )
        )
        session.commit()


def test_database_rejects_mismatched_test_case_revision_version(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_1_ID,
        revision_id=TEST_CASE_1_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000195"),
        path="/v1",
    )
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_2_ID,
        revision_id=TEST_CASE_2_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-000000000196"),
        path="/v2",
    )
    make_suite_service(factory, [SUITE_ID, SUITE_REVISION_1_ID, SUITE_EVENT_1_ID]).create(
        PROJECT_ID,
        name="Constraint suite",
        test_case_revision_ids=[TEST_CASE_1_REVISION_1_ID],
    )

    with Session(engine) as session, pytest.raises(IntegrityError):
        session.add(
            SuiteRevisionItemRow(
                suite_revision_id=SUITE_REVISION_1_ID,
                ordinal=1,
                project_id=PROJECT_ID,
                test_case_id=TEST_CASE_2_ID,
                test_case_revision_id=TEST_CASE_2_REVISION_1_ID,
                test_case_revision_version=2,
            )
        )
        session.commit()


def test_database_rejects_active_revision_from_another_suite(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    make_test_case(
        factory,
        project_id=PROJECT_ID,
        test_case_id=TEST_CASE_1_ID,
        revision_id=TEST_CASE_1_REVISION_1_ID,
        event_id=UUID("00000000-0000-4000-8000-0000000001A1"),
        path="/v1",
    )
    make_suite_service(factory, [SUITE_ID, SUITE_REVISION_1_ID, SUITE_EVENT_1_ID]).create(
        PROJECT_ID,
        name="First suite",
        test_case_revision_ids=[TEST_CASE_1_REVISION_1_ID],
    )
    make_suite_service(
        factory,
        [OTHER_SUITE_ID, OTHER_SUITE_REVISION_ID, OTHER_SUITE_EVENT_ID],
    ).create(
        PROJECT_ID,
        name="Second suite",
        test_case_revision_ids=[TEST_CASE_1_REVISION_1_ID],
    )

    with Session(engine) as session, pytest.raises(IntegrityError):
        session.execute(
            update(SuiteRow)
            .where(SuiteRow.id == SUITE_ID)
            .values(active_revision_id=OTHER_SUITE_REVISION_ID)
        )
        session.commit()
