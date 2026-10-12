from sqlalchemy.orm import Session

from sentinel.catalog.changes import ChangeEvent
from sentinel.persistence.models import ChangeEventRow


class SqlAlchemyChangeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: ChangeEvent) -> None:
        self._session.add(
            ChangeEventRow(
                id=event.id,
                project_id=event.project_id,
                kind=event.kind.value,
                subject_type=event.subject_type.value,
                subject_id=event.subject_id,
                before_ref=event.before_ref,
                after_ref=event.after_ref,
                summary=event.summary.to_document(),
                created_at=event.created_at,
            )
        )
