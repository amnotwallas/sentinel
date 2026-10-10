from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sentinel.catalog.changes import (
    ChangeEvent,
    ChangeEventKind,
    ChangeSubjectType,
    ChangeSummary,
)
from sentinel.catalog.projects import Project, ProjectNameConflict, ProjectService
from sentinel.persistence.catalog.unit_of_work import PostgresCatalogUnitOfWork
from sentinel.persistence.models import ChangeEventRow, ProjectRow

pytestmark = pytest.mark.integration


FIRST_ID = UUID("00000000-0000-4000-8000-000000000001")
SECOND_ID = UUID("00000000-0000-4000-8000-000000000002")
THIRD_ID = UUID("00000000-0000-4000-8000-000000000003")
NOW = datetime(2030, 1, 1, 12, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_catalog(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(delete(ChangeEventRow))
        connection.execute(delete(ProjectRow))


def project_service(
    engine: Engine,
    *,
    ids: list[UUID],
    times: list[datetime] | None = None,
) -> ProjectService:
    id_values = iter(ids)
    time_values = iter(times or [NOW] * len(ids))
    factory = sessionmaker(engine, expire_on_commit=False)
    return ProjectService(
        lambda: PostgresCatalogUnitOfWork(factory),
        ids=lambda: next(id_values),
        clock=lambda: next(time_values),
    )


def test_created_project_survives_a_new_service_and_session(engine: Engine) -> None:
    creator = project_service(engine, ids=[FIRST_ID])
    created = creator.create("Synthetic project")

    reader = project_service(engine, ids=[])

    assert reader.get(FIRST_ID) == created
    with Session(engine) as session:
        row = session.get(ProjectRow, FIRST_ID)
        assert row is not None
        assert row.name == "Synthetic project"
        assert row.state_version == 1


def test_duplicate_normalized_name_rolls_back_without_partial_rows(engine: Engine) -> None:
    projects = project_service(engine, ids=[FIRST_ID, SECOND_ID])
    projects.create("Caf\N{LATIN SMALL LETTER E WITH ACUTE}")

    with pytest.raises(ProjectNameConflict):
        projects.create(" Cafe\N{COMBINING ACUTE ACCENT} ")

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProjectRow)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEventRow)) == 0


def test_project_list_uses_created_at_and_id_keyset(engine: Engine) -> None:
    projects = project_service(
        engine,
        ids=[THIRD_ID, FIRST_ID, SECOND_ID],
        times=[NOW + timedelta(seconds=1), NOW, NOW],
    )
    projects.create("Third")
    projects.create("First")
    projects.create("Second")

    first_page = projects.list(limit=2, after=None)
    second_page = projects.list(limit=2, after=first_page.next_after)

    assert [project.id for project in first_page.items] == [FIRST_ID, SECOND_ID]
    assert first_page.next_after == (NOW, SECOND_ID)
    assert [project.id for project in second_page.items] == [THIRD_ID]
    assert second_page.next_after is None


def test_project_and_change_event_roll_back_in_one_transaction(engine: Engine) -> None:
    projects = project_service(engine, ids=[FIRST_ID])
    projects.create("Taken")
    factory = sessionmaker(engine, expire_on_commit=False)
    unit_of_work = PostgresCatalogUnitOfWork(factory)

    with pytest.raises(ProjectNameConflict), unit_of_work:
        unit_of_work.projects.add(Project(SECOND_ID, "Taken", NOW, None, 1))
        unit_of_work.changes.add(
            ChangeEvent(
                id=UUID("00000000-0000-4000-8000-000000000010"),
                project_id=SECOND_ID,
                kind=ChangeEventKind.ENVIRONMENT_CREATED,
                subject_type=ChangeSubjectType.ENVIRONMENT,
                subject_id=UUID("00000000-0000-4000-8000-000000000020"),
                before_ref=None,
                after_ref=UUID("00000000-0000-4000-8000-000000000021"),
                summary=ChangeSummary.from_values(["name"]),
                created_at=NOW,
            )
        )
        unit_of_work.commit()

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProjectRow)) == 1
        assert session.scalar(select(func.count()).select_from(ChangeEventRow)) == 0
