from datetime import UTC, datetime
from uuid import UUID

import pytest

from sentinel.catalog.projects import (
    Project,
    ProjectNameConflict,
    ProjectNotFound,
    ProjectService,
    ProjectValidationError,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2030, 1, 1, 12, 30, tzinfo=UTC)


class MemoryProjects:
    def __init__(self, projects: list[Project] | None = None) -> None:
        self.items = {project.id: project for project in projects or []}

    def add(self, project: Project) -> None:
        if any(existing.name == project.name for existing in self.items.values()):
            raise ProjectNameConflict
        self.items[project.id] = project

    def get(self, project_id: UUID) -> Project | None:
        return self.items.get(project_id)

    def list_after(
        self,
        *,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Project]:
        projects = sorted(self.items.values(), key=lambda item: (item.created_at, item.id))
        if after is not None:
            projects = [project for project in projects if (project.created_at, project.id) > after]
        return projects[:limit]


class MemoryUnitOfWork:
    def __init__(self, projects: MemoryProjects) -> None:
        self.projects = projects
        self.commits = 0

    def __enter__(self) -> "MemoryUnitOfWork":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


def service(
    projects: MemoryProjects | None = None,
) -> tuple[ProjectService, MemoryUnitOfWork]:
    unit_of_work = MemoryUnitOfWork(projects or MemoryProjects())
    return (
        ProjectService(lambda: unit_of_work, ids=lambda: PROJECT_ID, clock=lambda: NOW),
        unit_of_work,
    )


def test_create_project_normalizes_name_and_commits_once() -> None:
    projects = MemoryProjects()
    projects_service, unit_of_work = service(projects)

    project = projects_service.create("  Cafe\N{COMBINING ACUTE ACCENT} API  ")

    assert project == Project(
        id=PROJECT_ID,
        name="Caf\N{LATIN SMALL LETTER E WITH ACUTE} API",
        created_at=NOW,
        deleted_at=None,
        state_version=1,
    )
    assert projects.get(PROJECT_ID) == project
    assert unit_of_work.commits == 1


@pytest.mark.parametrize("name", ["", "   ", "bad\nname", "x" * 121])
def test_create_project_rejects_invalid_names_without_committing(name: str) -> None:
    projects_service, unit_of_work = service()

    with pytest.raises(ProjectValidationError):
        projects_service.create(name)

    assert unit_of_work.commits == 0


def test_create_project_rejects_duplicate_normalized_name() -> None:
    existing = Project(PROJECT_ID, "Caf\N{LATIN SMALL LETTER E WITH ACUTE}", NOW, None, 1)
    projects_service, unit_of_work = service(MemoryProjects([existing]))

    with pytest.raises(ProjectNameConflict):
        projects_service.create("Cafe\N{COMBINING ACUTE ACCENT}")

    assert unit_of_work.commits == 0


def test_get_project_hides_missing_identity_behind_domain_error() -> None:
    projects_service, _ = service()

    with pytest.raises(ProjectNotFound):
        projects_service.get(PROJECT_ID)


def test_list_projects_returns_ordered_page_and_continuation_key() -> None:
    first_id = UUID("00000000-0000-4000-8000-000000000001")
    second_id = UUID("00000000-0000-4000-8000-000000000002")
    third_id = UUID("00000000-0000-4000-8000-000000000003")
    projects = MemoryProjects(
        [
            Project(third_id, "Third", NOW, None, 1),
            Project(first_id, "First", NOW, None, 1),
            Project(second_id, "Second", NOW, None, 1),
        ]
    )
    projects_service, _ = service(projects)

    page = projects_service.list(limit=2, after=None)

    assert [project.id for project in page.items] == [first_id, second_id]
    assert page.next_after == (NOW, second_id)


@pytest.mark.parametrize("limit", [0, 101])
def test_list_projects_enforces_page_bounds_in_the_service(limit: int) -> None:
    projects_service, _ = service()

    with pytest.raises(ProjectValidationError):
        projects_service.list(limit=limit, after=None)
