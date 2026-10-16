from types import TracebackType

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sentinel.catalog.projects import ProjectNameConflict
from sentinel.persistence.catalog.changes import SqlAlchemyChangeRepository
from sentinel.persistence.catalog.environments import SqlAlchemyEnvironmentRepository
from sentinel.persistence.catalog.projects import SqlAlchemyProjectRepository
from sentinel.persistence.catalog.suites import SqlAlchemySuiteRepository
from sentinel.persistence.catalog.test_cases import SqlAlchemyTestCaseRepository


class PostgresCatalogUnitOfWork:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._session: Session | None = None

    def __enter__(self) -> "PostgresCatalogUnitOfWork":
        self._session = self._sessions()
        self.projects = SqlAlchemyProjectRepository(self._session)
        self.environments = SqlAlchemyEnvironmentRepository(self._session)
        self.test_cases = SqlAlchemyTestCaseRepository(self._session)
        self.suites = SqlAlchemySuiteRepository(self._session)
        self.changes = SqlAlchemyChangeRepository(self._session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        if exc_type is not None:
            self._session.rollback()
        self._session.close()
        self._session = None

    def commit(self) -> None:
        session = self._require_session()
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            diagnostic = getattr(error.orig, "diag", None)
            if getattr(diagnostic, "constraint_name", None) == "uq_projects_live_name":
                raise ProjectNameConflict from None
            raise

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        return self._session
