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
from sentinel.catalog.ports import CatalogUnitOfWorkFactory
from sentinel.catalog.projects import ProjectNotFound, normalize_project_name


class EnvironmentError(Exception):
    pass


class EnvironmentValidationError(EnvironmentError):
    pass


class EnvironmentNotFound(EnvironmentError):
    pass


class EnvironmentRevisionConflict(EnvironmentError):
    pass


class EnvironmentVersionExhausted(EnvironmentError):
    pass


@dataclass(frozen=True, slots=True)
class SecretReference:
    name: str

    def to_document(self) -> dict[str, str]:
        return {"$secret": self.name}


@dataclass(frozen=True, slots=True)
class TargetPolicy:
    allowed_hostnames: tuple[str, ...] = ()
    allowed_cidrs: tuple[str, ...] = ()
    denied_hostnames: tuple[str, ...] = ()
    denied_cidrs: tuple[str, ...] = ()
    allowed_ports: tuple[int, ...] | None = None

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "allowed_hostnames": list(self.allowed_hostnames),
            "allowed_cidrs": list(self.allowed_cidrs),
            "denied_hostnames": list(self.denied_hostnames),
            "denied_cidrs": list(self.denied_cidrs),
            "allowed_ports": list(self.allowed_ports) if self.allowed_ports is not None else None,
        }


@dataclass(frozen=True, slots=True)
class EnvironmentDocument:
    base_url: str
    variables: tuple[tuple[str, str], ...]
    secret_references: tuple[SecretReference, ...]
    target_policy: TargetPolicy

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "base_url": self.base_url,
            "variables": dict(self.variables),
            "secret_references": [reference.to_document() for reference in self.secret_references],
            "target_policy": self.target_policy.to_document(),
        }


@dataclass(frozen=True, slots=True)
class EnvironmentRevision:
    id: UUID
    environment_id: UUID
    version: int
    definition: EnvironmentDocument
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Environment:
    id: UUID
    project_id: UUID
    name: str
    active_revision_id: UUID
    active_revision: EnvironmentRevision
    state_version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EnvironmentPage:
    items: list[Environment]
    next_after: tuple[datetime, UUID] | None


DocumentValidator = Callable[[object], EnvironmentDocument]


class EnvironmentService:
    def __init__(
        self,
        unit_of_work: CatalogUnitOfWorkFactory,
        *,
        ids: Callable[[], UUID],
        clock: Callable[[], datetime],
        validate_document: DocumentValidator,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._ids = ids
        self._clock = clock
        self._validate_document = validate_document

    def create(self, project_id: UUID, *, name: str, definition: object) -> Environment:
        canonical_name = normalize_project_name(name)
        document = self._validate_document(definition)
        now = self._clock()
        environment_id = self._ids()
        revision = EnvironmentRevision(
            id=self._ids(),
            environment_id=environment_id,
            version=1,
            definition=document,
            created_at=now,
        )
        environment = Environment(
            id=environment_id,
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
            unit_of_work.environments.add(environment)
            unit_of_work.changes.add(
                ChangeEvent(
                    id=self._ids(),
                    project_id=project_id,
                    kind=ChangeEventKind.ENVIRONMENT_CREATED,
                    subject_type=ChangeSubjectType.ENVIRONMENT,
                    subject_id=environment.id,
                    before_ref=None,
                    after_ref=revision.id,
                    summary=ChangeSummary.from_values(
                        ["name", "base_url", "variables", "secret_references", "target_policy"]
                    ),
                    created_at=now,
                )
            )
            unit_of_work.commit()
        return environment

    def get(self, environment_id: UUID) -> Environment:
        with self._unit_of_work() as unit_of_work:
            environment = unit_of_work.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFound
        return environment

    def list(
        self,
        project_id: UUID,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> EnvironmentPage:
        if not 1 <= limit <= 100:
            raise EnvironmentValidationError("environment page limit is invalid")
        with self._unit_of_work() as unit_of_work:
            project = unit_of_work.projects.get(project_id)
            if project is None or project.deleted_at is not None:
                raise ProjectNotFound
            environments = unit_of_work.environments.list_after(
                project_id=project_id, after=after, limit=limit + 1
            )
        has_more = len(environments) > limit
        items = environments[:limit]
        next_after = (items[-1].created_at, items[-1].id) if has_more and items else None
        return EnvironmentPage(items=items, next_after=next_after)

    def update(
        self,
        environment_id: UUID,
        *,
        expected_state_version: int,
        name: str | None,
        definition: object | None,
    ) -> Environment:
        if name is None and definition is None:
            raise EnvironmentValidationError("empty environment update")
        canonical_name = normalize_project_name(name) if name is not None else None
        document = self._validate_document(definition) if definition is not None else None
        now = self._clock()
        with self._unit_of_work() as unit_of_work:
            current = unit_of_work.environments.get(environment_id, for_update=True)
            if current is None:
                raise EnvironmentNotFound
            if current.state_version != expected_state_version:
                raise EnvironmentRevisionConflict
            if current.state_version == 2_147_483_647 or (
                document is not None and current.active_revision.version == 2_147_483_647
            ):
                raise EnvironmentVersionExhausted
            revision = current.active_revision
            changed_fields: list[str] = []
            if canonical_name is not None:
                changed_fields.append("name")
            if document is not None:
                revision = EnvironmentRevision(
                    id=self._ids(),
                    environment_id=current.id,
                    version=current.active_revision.version + 1,
                    definition=document,
                    created_at=now,
                )
                changed_fields.extend(
                    ["base_url", "variables", "secret_references", "target_policy"]
                )
            updated = replace(
                current,
                name=canonical_name if canonical_name is not None else current.name,
                active_revision_id=revision.id,
                active_revision=revision,
                state_version=current.state_version + 1,
                updated_at=now,
            )
            unit_of_work.environments.replace(updated)
            unit_of_work.changes.add(
                ChangeEvent(
                    id=self._ids(),
                    project_id=current.project_id,
                    kind=ChangeEventKind.ENVIRONMENT_UPDATED,
                    subject_type=ChangeSubjectType.ENVIRONMENT,
                    subject_id=current.id,
                    before_ref=current.active_revision_id,
                    after_ref=revision.id,
                    summary=ChangeSummary.from_values(changed_fields),
                    created_at=now,
                )
            )
            unit_of_work.commit()
        return updated
