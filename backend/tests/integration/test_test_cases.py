from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.catalog.changes import ChangeEvent
from sentinel.catalog.test_cases import TestCaseRevisionConflict as RevisionConflict
from sentinel.catalog.test_cases import TestCaseService as Service
from sentinel.persistence.catalog.changes import SqlAlchemyChangeRepository
from sentinel.persistence.catalog.unit_of_work import PostgresCatalogUnitOfWork
from sentinel.persistence.models import (
    ChangeEventRow,
)
from sentinel.persistence.models import (
    TestCaseRevisionRow as TestCaseRevisionTable,
)
from sentinel.persistence.models import (
    TestCaseRow as TestCaseTable,
)
from sentinel.security.definition_policy import validate_test_definition

pytestmark = pytest.mark.integration

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000002")
TEST_CASE_ID = UUID("00000000-0000-4000-8000-000000000010")
REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000011")
EVENT_1_ID = UUID("00000000-0000-4000-8000-000000000012")
REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000013")
EVENT_2_ID = UUID("00000000-0000-4000-8000-000000000014")
REVISION_3_ID = UUID("00000000-0000-4000-8000-000000000015")
EVENT_3_ID = UUID("00000000-0000-4000-8000-000000000016")
NOW = datetime(2030, 1, 1, tzinfo=UTC)


def definition(*, path: str = "/health", unsafe: bool = False) -> dict[str, object]:
    return {
        "request": {
            "method": "GET",
            "path": path,
            "headers": [{"name": "X-Synthetic", "value": "fixture"}],
        },
        "assertions": [],
        "comparison_policy": {},
        "redaction": {},
        "allow_unsafe_replay": unsafe,
    }


class FailingChanges(SqlAlchemyChangeRepository):
    def add(self, event: ChangeEvent) -> None:
        raise RuntimeError("synthetic change-event failure")


class FailingChangeUnitOfWork(PostgresCatalogUnitOfWork):
    def __enter__(self) -> "FailingChangeUnitOfWork":
        super().__enter__()
        assert self._session is not None
        self.changes = FailingChanges(self._session)
        return self


def make_project(factory: sessionmaker[Session], project_id: UUID) -> None:
    from sentinel.catalog.projects import ProjectService

    ProjectService(
        lambda: PostgresCatalogUnitOfWork(factory), ids=lambda: project_id, clock=lambda: NOW
    ).create(f"Project {project_id.int}")


def test_test_case_revision_history_and_stale_update_are_atomic(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID, REVISION_2_ID, EVENT_2_ID])
    service = Service(
        lambda: PostgresCatalogUnitOfWork(factory),
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
    updated = service.update(
        TEST_CASE_ID,
        expected_state_version=1,
        name="Probe",
        definition=definition(path="/healthz"),
        unsafe_replay_acknowledgement=None,
    )

    assert created.active_revision.version == 1
    assert updated.active_revision.version == 2
    assert created.active_revision.definition.policy_fingerprint == (
        updated.active_revision.definition.policy_fingerprint
    )
    assert [
        item.version for item in service.revisions(TEST_CASE_ID, limit=100, after=None).items
    ] == [1, 2]

    with pytest.raises(RevisionConflict):
        service.update(
            TEST_CASE_ID,
            expected_state_version=1,
            name="Stale",
            definition=definition(path="/stale"),
            unsafe_replay_acknowledgement=None,
        )

    with Session(engine) as session:
        row = session.get(TestCaseTable, TEST_CASE_ID)
        assert row is not None
        assert row.active_revision_id == REVISION_2_ID
        assert row.state_version == 2
        assert session.scalar(select(func.count()).select_from(TestCaseRevisionTable)) == 2
        assert session.scalar(select(func.count()).select_from(ChangeEventRow)) == 2


def test_decimal_definition_numbers_round_trip_exactly_through_postgresql(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID])
    service = Service(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    )
    decimal_definition = definition()
    decimal_definition["assertions"] = [
        {
            "id": "00000000-0000-4000-8000-000000000099",
            "severity": "required",
            "kind": "json_equals",
            "pointer": "/amount",
            "expected": Decimal("0.123456789012345678901"),
        }
    ]

    created = service.create(
        PROJECT_ID,
        name="Decimal probe",
        definition=decimal_definition,
        unsafe_replay_acknowledgement=None,
    )
    loaded = service.get(created.id)

    assertions = loaded.active_revision.definition.document["assertions"]
    assert isinstance(assertions, tuple)
    first = assertions[0]
    assert isinstance(first, Mapping)
    assert first["expected"] == Decimal("0.123456789012345678901")


def test_test_case_update_rolls_back_revision_and_pointer_on_change_failure(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    create_ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID])
    Service(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(create_ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    ).create(
        PROJECT_ID,
        name="Probe",
        definition=definition(),
        unsafe_replay_acknowledgement=None,
    )
    update_ids = iter([REVISION_2_ID, EVENT_2_ID])
    failing = Service(
        lambda: FailingChangeUnitOfWork(factory),
        ids=lambda: next(update_ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    )

    with pytest.raises(RuntimeError, match="synthetic change-event failure"):
        failing.update(
            TEST_CASE_ID,
            expected_state_version=1,
            name="Changed",
            definition=definition(path="/changed"),
            unsafe_replay_acknowledgement=None,
        )

    with Session(engine) as session:
        row = session.get(TestCaseTable, TEST_CASE_ID)
        assert row is not None
        assert row.active_revision_id == REVISION_1_ID
        assert row.state_version == 1
        assert session.scalar(select(func.count()).select_from(TestCaseRevisionTable)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEventRow)) == 1


def test_test_case_create_rolls_back_identity_revision_and_event_together(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID])
    failing = Service(
        lambda: FailingChangeUnitOfWork(factory),
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    )

    with pytest.raises(RuntimeError, match="synthetic change-event failure"):
        failing.create(
            PROJECT_ID,
            name="Probe",
            definition=definition(),
            unsafe_replay_acknowledgement=None,
        )

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(TestCaseTable)) == 0
        assert session.scalar(select(func.count()).select_from(TestCaseRevisionTable)) == 0
        assert session.scalar(select(func.count()).select_from(ChangeEventRow)) == 0


def test_test_case_lists_are_isolated_by_project(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    make_project(factory, OTHER_PROJECT_ID)
    first_ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID])
    service = Service(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(first_ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    )
    service.create(
        PROJECT_ID,
        name="First project",
        definition=definition(),
        unsafe_replay_acknowledgement=None,
    )
    second_ids = iter(
        [
            UUID("00000000-0000-4000-8000-000000000020"),
            UUID("00000000-0000-4000-8000-000000000021"),
            UUID("00000000-0000-4000-8000-000000000022"),
        ]
    )
    Service(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(second_ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    ).create(
        OTHER_PROJECT_ID,
        name="Other project",
        definition=definition(path="/other"),
        unsafe_replay_acknowledgement=None,
    )

    assert [item.id for item in service.list(PROJECT_ID, limit=100, after=None).items] == [
        TEST_CASE_ID
    ]


def test_test_case_unsafe_replay_consent_is_persisted_without_resolving_secrets(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID])
    service = Service(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    )

    secret_canary = "must-not-be-persisted-secret-value"
    monkeypatch.setenv("SENTINEL_SECRET_API_TOKEN", secret_canary)
    unsafe_definition = definition(unsafe=True)
    unsafe_definition["request"] = {
        "method": "POST",
        "path": "/write",
        "headers": [{"name": "Authorization", "value": {"$secret": "API_TOKEN"}}],
    }
    created = service.create(
        PROJECT_ID,
        name="Unsafe synthetic probe",
        definition=unsafe_definition,
        unsafe_replay_acknowledgement="duplicate_effects_possible",
    )

    assert created.active_revision.unsafe_replay_acknowledged_at == NOW
    with Session(engine) as session:
        row = session.get(TestCaseRevisionTable, REVISION_1_ID)
        assert row is not None
        assert row.unsafe_replay_acknowledgement == "duplicate_effects_possible"
        request = row.definition["request"]
        assert isinstance(request, dict)
        assert request["headers"] == [{"name": "authorization", "value": {"$secret": "API_TOKEN"}}]
        assert secret_canary not in str(row.definition)


def test_concurrent_same_etag_has_one_success_and_one_conflict(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    create_ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID])
    Service(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(create_ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    ).create(
        PROJECT_ID,
        name="Probe",
        definition=definition(),
        unsafe_replay_acknowledgement=None,
    )

    def revise(revision_id: UUID, event_id: UUID) -> str:
        ids = iter([revision_id, event_id])
        service = Service(
            lambda: PostgresCatalogUnitOfWork(factory),
            ids=lambda: next(ids),
            clock=lambda: NOW,
            validate_document=validate_test_definition,
        )
        try:
            service.update(
                TEST_CASE_ID,
                expected_state_version=1,
                name="Concurrent",
                definition=definition(path=f"/revision-{revision_id}"),
                unsafe_replay_acknowledgement=None,
            )
        except RevisionConflict:
            return "conflict"
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                revise,
                (REVISION_2_ID, REVISION_3_ID),
                (EVENT_2_ID, EVENT_3_ID),
            )
        )
    assert sorted(outcomes) == ["conflict", "success"]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(TestCaseRevisionTable)) == 2


def test_active_revision_pointer_must_belong_to_the_same_test_case(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    make_project(factory, PROJECT_ID)
    first_ids = iter([TEST_CASE_ID, REVISION_1_ID, EVENT_1_ID])
    Service(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(first_ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    ).create(
        PROJECT_ID,
        name="First",
        definition=definition(),
        unsafe_replay_acknowledgement=None,
    )
    other_test_case_id = UUID("00000000-0000-4000-8000-000000000020")
    other_revision_id = UUID("00000000-0000-4000-8000-000000000021")
    second_ids = iter(
        [
            other_test_case_id,
            other_revision_id,
            UUID("00000000-0000-4000-8000-000000000022"),
        ]
    )
    Service(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(second_ids),
        clock=lambda: NOW,
        validate_document=validate_test_definition,
    ).create(
        PROJECT_ID,
        name="Second",
        definition=definition(path="/other"),
        unsafe_replay_acknowledgement=None,
    )

    with Session(engine) as session, pytest.raises(IntegrityError):
        session.execute(
            update(TestCaseTable)
            .where(TestCaseTable.id == TEST_CASE_ID)
            .values(active_revision_id=other_revision_id)
        )
        session.commit()
