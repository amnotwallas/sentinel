from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.catalog.changes import ChangeEvent
from sentinel.catalog.environments import EnvironmentRevisionConflict, EnvironmentService
from sentinel.catalog.projects import ProjectService
from sentinel.persistence.catalog.changes import SqlAlchemyChangeRepository
from sentinel.persistence.catalog.unit_of_work import PostgresCatalogUnitOfWork
from sentinel.persistence.models import ChangeEventRow, EnvironmentRevisionRow, EnvironmentRow
from sentinel.security.definition_policy import validate_environment_document

pytestmark = pytest.mark.integration

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
ENVIRONMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000011")
EVENT_1_ID = UUID("00000000-0000-4000-8000-000000000012")
REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000013")
EVENT_2_ID = UUID("00000000-0000-4000-8000-000000000014")
NOW = datetime(2030, 1, 1, tzinfo=UTC)


class FailingChanges(SqlAlchemyChangeRepository):
    def add(self, event: ChangeEvent) -> None:
        raise RuntimeError("synthetic change-event failure")


class FailingChangeUnitOfWork(PostgresCatalogUnitOfWork):
    def __enter__(self) -> "FailingChangeUnitOfWork":
        super().__enter__()
        assert self._session is not None
        self.changes = FailingChanges(self._session)
        return self


def test_environment_revisions_are_immutable_and_activated_atomically(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ProjectService(
        lambda: PostgresCatalogUnitOfWork(factory), ids=lambda: PROJECT_ID, clock=lambda: NOW
    ).create("Synthetic")
    ids = iter([ENVIRONMENT_ID, REVISION_1_ID, EVENT_1_ID, REVISION_2_ID, EVENT_2_ID])
    service = EnvironmentService(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_environment_document,
    )

    service.create(PROJECT_ID, name="Production", definition={"base_url": "https://v1.example"})
    service.update(
        ENVIRONMENT_ID,
        expected_state_version=1,
        name=None,
        definition={"base_url": "https://v2.example"},
    )

    with Session(engine) as session:
        environment = session.get(EnvironmentRow, ENVIRONMENT_ID)
        revisions = session.scalars(
            select(EnvironmentRevisionRow).order_by(EnvironmentRevisionRow.version)
        ).all()
        assert environment is not None
        assert environment.active_revision_id == REVISION_2_ID
        assert environment.state_version == 2
        assert session.scalar(select(func.count()).select_from(EnvironmentRevisionRow)) == 2
        assert [revision.definition["base_url"] for revision in revisions] == [
            "https://v1.example/",
            "https://v2.example/",
        ]

    with pytest.raises(EnvironmentRevisionConflict):
        service.update(
            ENVIRONMENT_ID,
            expected_state_version=1,
            name="Stale",
            definition={"base_url": "https://stale.example"},
        )

    with Session(engine) as session:
        environment = session.get(EnvironmentRow, ENVIRONMENT_ID)
        assert environment is not None
        assert environment.name == "Production"
        assert environment.state_version == 2
        assert session.scalar(select(func.count()).select_from(EnvironmentRevisionRow)) == 2
        assert session.scalar(select(func.count()).select_from(ChangeEventRow)) == 2


def test_environment_update_rolls_back_revision_and_pointer_when_change_event_fails(
    engine: Engine,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ProjectService(
        lambda: PostgresCatalogUnitOfWork(factory), ids=lambda: PROJECT_ID, clock=lambda: NOW
    ).create("Synthetic")
    create_ids = iter([ENVIRONMENT_ID, REVISION_1_ID, EVENT_1_ID])
    EnvironmentService(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(create_ids),
        clock=lambda: NOW,
        validate_document=validate_environment_document,
    ).create(PROJECT_ID, name="Production", definition={"base_url": "https://v1.example"})
    update_ids = iter([REVISION_2_ID, EVENT_2_ID])
    failing_service = EnvironmentService(
        lambda: FailingChangeUnitOfWork(factory),
        ids=lambda: next(update_ids),
        clock=lambda: NOW,
        validate_document=validate_environment_document,
    )

    with pytest.raises(RuntimeError, match="synthetic change-event failure"):
        failing_service.update(
            ENVIRONMENT_ID,
            expected_state_version=1,
            name=None,
            definition={"base_url": "https://v2.example"},
        )

    with Session(engine) as session:
        environment = session.get(EnvironmentRow, ENVIRONMENT_ID)
        assert environment is not None
        assert environment.active_revision_id == REVISION_1_ID
        assert environment.state_version == 1
        assert session.scalar(select(func.count()).select_from(EnvironmentRevisionRow)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEventRow)) == 1


def test_concurrent_same_etag_environment_updates_have_one_success_and_one_conflict(
    engine: Engine,
) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ProjectService(
        lambda: PostgresCatalogUnitOfWork(factory), ids=lambda: PROJECT_ID, clock=lambda: NOW
    ).create("Synthetic")
    create_ids = iter([ENVIRONMENT_ID, REVISION_1_ID, EVENT_1_ID])
    EnvironmentService(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(create_ids),
        clock=lambda: NOW,
        validate_document=validate_environment_document,
    ).create(PROJECT_ID, name="Production", definition={"base_url": "https://v1.example"})

    def revise(revision_id: UUID, event_id: UUID) -> str:
        ids = iter([revision_id, event_id])
        service = EnvironmentService(
            lambda: PostgresCatalogUnitOfWork(factory),
            ids=lambda: next(ids),
            clock=lambda: NOW,
            validate_document=validate_environment_document,
        )
        try:
            service.update(
                ENVIRONMENT_ID,
                expected_state_version=1,
                name=None,
                definition={"base_url": f"https://{revision_id}.example"},
            )
        except EnvironmentRevisionConflict:
            return "conflict"
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                revise,
                (REVISION_2_ID, UUID("00000000-0000-4000-8000-000000000015")),
                (EVENT_2_ID, UUID("00000000-0000-4000-8000-000000000016")),
            )
        )

    assert sorted(outcomes) == ["conflict", "success"]
    with Session(engine) as session:
        environment = session.get(EnvironmentRow, ENVIRONMENT_ID)
        assert environment is not None
        assert environment.state_version == 2
        assert session.scalar(select(func.count()).select_from(EnvironmentRevisionRow)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(ChangeEventRow)
                .where(ChangeEventRow.kind == "environment_updated")
            )
            == 1
        )


def test_active_revision_pointer_must_belong_to_the_same_environment(engine: Engine) -> None:
    factory = sessionmaker(engine, expire_on_commit=False)
    ProjectService(
        lambda: PostgresCatalogUnitOfWork(factory), ids=lambda: PROJECT_ID, clock=lambda: NOW
    ).create("Synthetic")
    ids = iter(
        [
            ENVIRONMENT_ID,
            REVISION_1_ID,
            EVENT_1_ID,
            UUID("00000000-0000-4000-8000-000000000020"),
            UUID("00000000-0000-4000-8000-000000000021"),
            UUID("00000000-0000-4000-8000-000000000022"),
        ]
    )
    service = EnvironmentService(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_environment_document,
    )
    service.create(
        PROJECT_ID,
        name="First",
        definition={"base_url": "https://first.example"},
    )
    second = service.create(
        PROJECT_ID,
        name="Second",
        definition={"base_url": "https://second.example"},
    )

    with Session(engine) as session, pytest.raises(IntegrityError):
        session.execute(
            update(EnvironmentRow)
            .where(EnvironmentRow.id == ENVIRONMENT_ID)
            .values(active_revision_id=second.active_revision_id)
        )
        session.commit()
