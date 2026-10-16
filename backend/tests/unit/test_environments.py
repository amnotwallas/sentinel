from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from sentinel.catalog.environments import (
    Environment,
    EnvironmentRevisionConflict,
    EnvironmentService,
    EnvironmentVersionExhausted,
)
from sentinel.catalog.projects import Project
from sentinel.security.definition_policy import validate_environment_document

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
ENVIRONMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
REVISION_1_ID = UUID("00000000-0000-4000-8000-000000000011")
EVENT_1_ID = UUID("00000000-0000-4000-8000-000000000012")
REVISION_2_ID = UUID("00000000-0000-4000-8000-000000000013")
EVENT_2_ID = UUID("00000000-0000-4000-8000-000000000014")
NOW = datetime(2030, 1, 1, tzinfo=UTC)


class MemoryProjects:
    def add(self, project: Project) -> None:
        return None

    def get(self, project_id: UUID) -> Project | None:
        if project_id != PROJECT_ID:
            return None
        return Project(PROJECT_ID, "Synthetic", NOW, None, 1)

    def list_after(self, *, after: tuple[datetime, UUID] | None, limit: int) -> list[Project]:
        return []


class MemoryEnvironments:
    def __init__(self) -> None:
        self.items: dict[UUID, Environment] = {}

    def add(self, environment: Environment) -> None:
        self.items[environment.id] = environment

    def get(self, environment_id: UUID, *, for_update: bool = False) -> Environment | None:
        return self.items.get(environment_id)

    def replace(self, environment: Environment) -> None:
        self.items[environment.id] = environment

    def list_after(
        self,
        *,
        project_id: UUID,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Environment]:
        items = sorted(
            (item for item in self.items.values() if item.project_id == project_id),
            key=lambda item: (item.created_at, item.id),
        )
        if after is not None:
            items = [item for item in items if (item.created_at, item.id) > after]
        return items[:limit]


class MemoryChanges:
    def __init__(self) -> None:
        self.items: list[object] = []

    def add(self, event: object) -> None:
        self.items.append(event)


class MemoryUnitOfWork:
    def __init__(self) -> None:
        self.projects = MemoryProjects()
        self.environments = MemoryEnvironments()
        self.changes = MemoryChanges()
        self.commits = 0

    def __enter__(self) -> "MemoryUnitOfWork":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


def test_create_and_replace_environment_definition_preserves_revision_one() -> None:
    unit_of_work = MemoryUnitOfWork()
    ids = iter([ENVIRONMENT_ID, REVISION_1_ID, EVENT_1_ID, REVISION_2_ID, EVENT_2_ID])
    times = iter([NOW, NOW + timedelta(seconds=1)])
    service = EnvironmentService(
        lambda: unit_of_work,
        ids=lambda: next(ids),
        clock=lambda: next(times),
        validate_document=validate_environment_document,
    )

    created = service.create(
        PROJECT_ID,
        name=" Production ",
        definition={"base_url": "https://example.com"},
    )
    original_revision = created.active_revision
    updated = service.update(
        ENVIRONMENT_ID,
        expected_state_version=1,
        name=None,
        definition={"base_url": "https://example.com/v2"},
    )

    assert created.name == "Production"
    assert original_revision.version == 1
    assert original_revision.definition.base_url == "https://example.com/"
    assert updated.active_revision.version == 2
    assert updated.active_revision.definition.base_url == "https://example.com/v2/"
    assert original_revision.definition.base_url == "https://example.com/"
    assert updated.state_version == 2
    assert unit_of_work.commits == 2
    assert len(unit_of_work.changes.items) == 2


def test_stale_environment_update_does_not_write() -> None:
    unit_of_work = MemoryUnitOfWork()
    ids = iter([ENVIRONMENT_ID, REVISION_1_ID, EVENT_1_ID])
    service = EnvironmentService(
        lambda: unit_of_work,
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_environment_document,
    )
    service.create(PROJECT_ID, name="Production", definition={"base_url": "https://example.com"})

    with pytest.raises(EnvironmentRevisionConflict):
        service.update(
            ENVIRONMENT_ID,
            expected_state_version=99,
            name="Changed",
            definition=None,
        )

    assert unit_of_work.commits == 1
    assert len(unit_of_work.changes.items) == 1


def test_get_list_and_name_only_update_preserve_active_revision() -> None:
    unit_of_work = MemoryUnitOfWork()
    ids = iter([ENVIRONMENT_ID, REVISION_1_ID, EVENT_1_ID, EVENT_2_ID])
    service = EnvironmentService(
        lambda: unit_of_work,
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_environment_document,
    )
    created = service.create(
        PROJECT_ID, name="Production", definition={"base_url": "https://example.com"}
    )

    updated = service.update(
        ENVIRONMENT_ID,
        expected_state_version=1,
        name="Primary",
        definition=None,
    )

    assert service.get(ENVIRONMENT_ID) == updated
    assert service.list(PROJECT_ID, limit=50, after=None).items == [updated]
    assert updated.active_revision_id == created.active_revision_id
    assert updated.active_revision.version == 1
    assert updated.state_version == 2


@pytest.mark.parametrize(
    ("state_version", "revision_version"),
    [(2_147_483_647, 1), (1, 2_147_483_647)],
)
def test_environment_update_rejects_version_exhaustion_before_writing(
    state_version: int,
    revision_version: int,
) -> None:
    unit_of_work = MemoryUnitOfWork()
    ids = iter([ENVIRONMENT_ID, REVISION_1_ID, EVENT_1_ID, REVISION_2_ID, EVENT_2_ID])
    service = EnvironmentService(
        lambda: unit_of_work,
        ids=lambda: next(ids),
        clock=lambda: NOW,
        validate_document=validate_environment_document,
    )
    created = service.create(
        PROJECT_ID,
        name="Production",
        definition={"base_url": "https://example.com"},
    )
    exhausted = replace(
        created,
        state_version=state_version,
        active_revision=replace(created.active_revision, version=revision_version),
    )
    unit_of_work.environments.items[ENVIRONMENT_ID] = exhausted

    with pytest.raises(EnvironmentVersionExhausted):
        service.update(
            ENVIRONMENT_ID,
            expected_state_version=state_version,
            name=None,
            definition={"base_url": "https://v2.example.com"},
        )

    assert unit_of_work.commits == 1
    assert len(unit_of_work.changes.items) == 1
