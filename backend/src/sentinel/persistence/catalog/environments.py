from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from sentinel.catalog.environments import Environment, EnvironmentRevision
from sentinel.persistence.models import EnvironmentRevisionRow, EnvironmentRow
from sentinel.security.definition_policy import validate_environment_document


class SqlAlchemyEnvironmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, environment: Environment) -> None:
        self._session.add(
            EnvironmentRow(
                id=environment.id,
                project_id=environment.project_id,
                name=environment.name,
                active_revision_id=environment.active_revision_id,
                state_version=environment.state_version,
                created_at=environment.created_at,
                updated_at=environment.updated_at,
            )
        )
        # The active-revision FK is deferred, so the identity can be inserted
        # before its first immutable revision. The owning FK on the revision is
        # intentionally immediate and therefore requires this explicit flush.
        self._session.flush()
        self._session.add(self._revision_row(environment.active_revision))

    def get(self, environment_id: UUID, *, for_update: bool = False) -> Environment | None:
        statement = select(EnvironmentRow).where(EnvironmentRow.id == environment_id)
        if for_update:
            statement = statement.with_for_update()
        row = self._session.scalar(statement)
        if row is None:
            return None
        revision = self._session.get(EnvironmentRevisionRow, row.active_revision_id)
        if revision is None:
            raise RuntimeError("active environment revision is missing")
        return self._to_domain(row, revision)

    def replace(self, environment: Environment) -> None:
        row = self._session.get(EnvironmentRow, environment.id)
        if row is None:
            raise RuntimeError("environment is missing")
        if self._session.get(EnvironmentRevisionRow, environment.active_revision_id) is None:
            self._session.add(self._revision_row(environment.active_revision))
        row.name = environment.name
        row.active_revision_id = environment.active_revision_id
        row.state_version = environment.state_version
        row.updated_at = environment.updated_at

    def list_after(
        self,
        *,
        project_id: UUID,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Environment]:
        statement = select(EnvironmentRow).where(EnvironmentRow.project_id == project_id)
        if after is not None:
            created_at, environment_id = after
            statement = statement.where(
                or_(
                    EnvironmentRow.created_at > created_at,
                    and_(
                        EnvironmentRow.created_at == created_at,
                        EnvironmentRow.id > environment_id,
                    ),
                )
            )
        rows = self._session.scalars(
            statement.order_by(EnvironmentRow.created_at, EnvironmentRow.id).limit(limit)
        )
        environments: list[Environment] = []
        for row in rows:
            revision = self._session.get(EnvironmentRevisionRow, row.active_revision_id)
            if revision is None:
                raise RuntimeError("active environment revision is missing")
            environments.append(self._to_domain(row, revision))
        return environments

    @staticmethod
    def _revision_row(revision: EnvironmentRevision) -> EnvironmentRevisionRow:
        return EnvironmentRevisionRow(
            id=revision.id,
            environment_id=revision.environment_id,
            version=revision.version,
            definition=revision.definition.to_document(),
            created_at=revision.created_at,
        )

    @staticmethod
    def _to_domain(row: EnvironmentRow, revision: EnvironmentRevisionRow) -> Environment:
        domain_revision = EnvironmentRevision(
            id=revision.id,
            environment_id=revision.environment_id,
            version=revision.version,
            definition=validate_environment_document(revision.definition),
            created_at=revision.created_at,
        )
        return Environment(
            id=row.id,
            project_id=row.project_id,
            name=row.name,
            active_revision_id=row.active_revision_id,
            active_revision=domain_revision,
            state_version=row.state_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
