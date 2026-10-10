import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sentinel.catalog.ports import UnitOfWorkFactory


class ProjectError(Exception):
    pass


class ProjectValidationError(ProjectError):
    pass


class ProjectNameConflict(ProjectError):
    pass


class ProjectNotFound(ProjectError):
    pass


@dataclass(frozen=True, slots=True)
class Project:
    id: UUID
    name: str
    created_at: datetime
    deleted_at: datetime | None
    state_version: int


@dataclass(frozen=True, slots=True)
class ProjectPage:
    items: list[Project]
    next_after: tuple[datetime, UUID] | None


def normalize_project_name(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.strip(" "))
    if not 1 <= len(normalized) <= 120:
        raise ProjectValidationError("project name length is invalid")
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise ProjectValidationError("project name contains a control character")
    return normalized


class ProjectService:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        *,
        ids: Callable[[], UUID],
        clock: Callable[[], datetime],
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ids = ids
        self._clock = clock

    def create(self, name: str) -> Project:
        project = Project(
            id=self._ids(),
            name=normalize_project_name(name),
            created_at=self._clock(),
            deleted_at=None,
            state_version=1,
        )
        with self._unit_of_work() as unit_of_work:
            unit_of_work.projects.add(project)
            unit_of_work.commit()
        return project

    def get(self, project_id: UUID) -> Project:
        with self._unit_of_work() as unit_of_work:
            project = unit_of_work.projects.get(project_id)
        if project is None or project.deleted_at is not None:
            raise ProjectNotFound
        return project

    def list(
        self,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> ProjectPage:
        if not 1 <= limit <= 100:
            raise ProjectValidationError("project page limit is invalid")
        with self._unit_of_work() as unit_of_work:
            projects = unit_of_work.projects.list_after(after=after, limit=limit + 1)
        has_more = len(projects) > limit
        items = projects[:limit]
        next_after = (items[-1].created_at, items[-1].id) if has_more and items else None
        return ProjectPage(items=items, next_after=next_after)
