from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import TYPE_CHECKING, Protocol, Self
from uuid import UUID

if TYPE_CHECKING:
    from sentinel.catalog.changes import ChangeEvent
    from sentinel.catalog.environments import Environment
    from sentinel.catalog.projects import Project


class ProjectRepository(Protocol):
    def add(self, project: "Project") -> None: ...

    def get(self, project_id: UUID) -> "Project | None": ...

    def list_after(
        self,
        *,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list["Project"]: ...


class ChangeRepository(Protocol):
    def add(self, event: "ChangeEvent") -> None: ...


class EnvironmentRepository(Protocol):
    def add(self, environment: "Environment") -> None: ...

    def get(self, environment_id: UUID, *, for_update: bool = False) -> "Environment | None": ...

    def replace(self, environment: "Environment") -> None: ...

    def list_after(
        self,
        *,
        project_id: UUID,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list["Environment"]: ...


class ProjectUnitOfWork(Protocol):
    @property
    def projects(self) -> ProjectRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class CatalogUnitOfWork(ProjectUnitOfWork, Protocol):
    @property
    def changes(self) -> ChangeRepository: ...

    @property
    def environments(self) -> EnvironmentRepository: ...


UnitOfWorkFactory = Callable[[], ProjectUnitOfWork]
CatalogUnitOfWorkFactory = Callable[[], CatalogUnitOfWork]
