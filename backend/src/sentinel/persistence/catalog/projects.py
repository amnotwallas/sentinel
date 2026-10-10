from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from sentinel.catalog.projects import Project
from sentinel.persistence.models import ProjectRow


class SqlAlchemyProjectRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, project: Project) -> None:
        self._session.add(
            ProjectRow(
                id=project.id,
                name=project.name,
                state_version=project.state_version,
                created_at=project.created_at,
                deleted_at=project.deleted_at,
            )
        )

    def get(self, project_id: UUID) -> Project | None:
        row = self._session.scalar(
            select(ProjectRow).where(
                ProjectRow.id == project_id,
                ProjectRow.deleted_at.is_(None),
            )
        )
        return self._to_domain(row) if row is not None else None

    def list_after(
        self,
        *,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Project]:
        statement = select(ProjectRow).where(ProjectRow.deleted_at.is_(None))
        if after is not None:
            created_at, project_id = after
            statement = statement.where(
                or_(
                    ProjectRow.created_at > created_at,
                    and_(ProjectRow.created_at == created_at, ProjectRow.id > project_id),
                )
            )
        rows = self._session.scalars(
            statement.order_by(ProjectRow.created_at, ProjectRow.id).limit(limit)
        )
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: ProjectRow) -> Project:
        return Project(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            deleted_at=row.deleted_at,
            state_version=row.state_version,
        )
