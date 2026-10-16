from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("state_version BETWEEN 1 AND 2147483647", name="project_state_version"),
        Index(
            "uq_projects_live_name",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_projects_list", "created_at", "id", postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    state_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnvironmentRow(Base):
    __tablename__ = "environments"
    __table_args__ = (
        CheckConstraint("state_version BETWEEN 1 AND 2147483647", name="environment_state_version"),
        Index("ix_environments_project_list", "project_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    active_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "environment_revisions.id",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            name="fk_environments_active_revision",
        )
    )
    state_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnvironmentRevisionRow(Base):
    __tablename__ = "environment_revisions"
    __table_args__ = (
        CheckConstraint("version BETWEEN 1 AND 2147483647", name="environment_revision_version"),
        Index("uq_environment_revisions_version", "environment_id", "version", unique=True),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    environment_id: Mapped[UUID] = mapped_column(ForeignKey("environments.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TestCaseRow(Base):
    __test__ = False
    __tablename__ = "test_cases"
    __table_args__ = (
        CheckConstraint("state_version BETWEEN 1 AND 2147483647", name="test_case_state_version"),
        UniqueConstraint("id", "project_id", name="uq_test_cases_identity_project"),
        ForeignKeyConstraint(
            ["active_revision_id", "id"],
            ["test_case_revisions.id", "test_case_revisions.test_case_id"],
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            name="fk_test_cases_active_revision",
        ),
        Index("ix_test_cases_project_list", "project_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    active_revision_id: Mapped[UUID]
    state_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TestCaseRevisionRow(Base):
    __test__ = False
    __tablename__ = "test_case_revisions"
    __table_args__ = (
        CheckConstraint("version BETWEEN 1 AND 2147483647", name="test_case_revision_version"),
        CheckConstraint(
            "(unsafe_replay_acknowledgement IS NULL AND unsafe_replay_acknowledged_at IS NULL) "
            "OR (unsafe_replay_acknowledgement = 'duplicate_effects_possible' "
            "AND unsafe_replay_acknowledged_at IS NOT NULL)",
            name="test_case_replay_ack_shape",
        ),
        UniqueConstraint("id", "test_case_id", name="uq_test_case_revisions_identity_owner"),
        UniqueConstraint(
            "id",
            "test_case_id",
            "version",
            name="uq_test_case_revisions_identity_owner_version",
        ),
        Index("uq_test_case_revisions_version", "test_case_id", "version", unique=True),
        Index("ix_test_case_revisions_history", "test_case_id", "version", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    test_case_id: Mapped[UUID] = mapped_column(ForeignKey("test_cases.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    policy_fingerprint: Mapped[str] = mapped_column(String(64))
    unsafe_replay_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsafe_replay_acknowledgement: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SuiteRow(Base):
    __tablename__ = "suites"
    __table_args__ = (
        CheckConstraint("state_version BETWEEN 1 AND 2147483647", name="suite_state_version"),
        UniqueConstraint("id", "project_id", name="uq_suites_identity_project"),
        ForeignKeyConstraint(
            ["active_revision_id", "id"],
            ["suite_revisions.id", "suite_revisions.suite_id"],
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            name="fk_suites_active_revision",
        ),
        Index("ix_suites_project_list", "project_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    active_revision_id: Mapped[UUID]
    state_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SuiteRevisionRow(Base):
    __tablename__ = "suite_revisions"
    __table_args__ = (
        CheckConstraint("version BETWEEN 1 AND 2147483647", name="suite_revision_version"),
        ForeignKeyConstraint(
            ["suite_id", "project_id"],
            ["suites.id", "suites.project_id"],
            ondelete="RESTRICT",
            name="fk_suite_revisions_suite_project",
        ),
        UniqueConstraint("id", "suite_id", name="uq_suite_revisions_identity_owner"),
        UniqueConstraint("id", "project_id", name="uq_suite_revisions_identity_project"),
        Index("uq_suite_revisions_version", "suite_id", "version", unique=True),
        Index("ix_suite_revisions_history", "suite_id", "version", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    suite_id: Mapped[UUID]
    project_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SuiteRevisionItemRow(Base):
    __tablename__ = "suite_revision_items"
    __table_args__ = (
        CheckConstraint("ordinal BETWEEN 0 AND 99", name="suite_revision_item_ordinal"),
        CheckConstraint(
            "test_case_revision_version BETWEEN 1 AND 2147483647",
            name="suite_revision_item_version",
        ),
        ForeignKeyConstraint(
            ["suite_revision_id", "project_id"],
            ["suite_revisions.id", "suite_revisions.project_id"],
            ondelete="RESTRICT",
            name="fk_suite_revision_items_revision_project",
        ),
        ForeignKeyConstraint(
            ["test_case_id", "project_id"],
            ["test_cases.id", "test_cases.project_id"],
            ondelete="RESTRICT",
            name="fk_suite_revision_items_test_case_project",
        ),
        ForeignKeyConstraint(
            ["test_case_revision_id", "test_case_id", "test_case_revision_version"],
            [
                "test_case_revisions.id",
                "test_case_revisions.test_case_id",
                "test_case_revisions.version",
            ],
            ondelete="RESTRICT",
            name="fk_suite_revision_items_test_case_revision_version",
        ),
        UniqueConstraint("suite_revision_id", "test_case_id", name="uq_suite_revision_items_case"),
        Index("ix_suite_revision_items_revision_order", "suite_revision_id", "ordinal"),
    )

    suite_revision_id: Mapped[UUID] = mapped_column(primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[UUID]
    test_case_id: Mapped[UUID]
    test_case_revision_id: Mapped[UUID]
    test_case_revision_version: Mapped[int] = mapped_column(Integer)


class ChangeEventRow(Base):
    __tablename__ = "change_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('environment_created','environment_updated','test_case_created',"
            "'test_case_revised','suite_created','suite_revised','baseline_activated')",
            name="change_event_kind",
        ),
        CheckConstraint(
            "subject_type IN ('environment','test_case','suite','baseline')",
            name="change_event_subject_type",
        ),
        Index("ix_change_events_project_time", "project_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(32))
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[UUID]
    before_ref: Mapped[UUID | None]
    after_ref: Mapped[UUID | None]
    summary: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExecutionRow(Base):
    """Minimal internal probe envelope; catalog revision references arrive later."""

    __tablename__ = "executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','failed')", name="execution_status"
        ),
        CheckConstraint("verdict IS NULL OR verdict = 'not_evaluated'", name="execution_verdict"),
        CheckConstraint(
            "(status IN ('completed','failed')) = (finished_at IS NOT NULL)",
            name="execution_terminal_time",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    verdict: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("state IN ('pending','leased','succeeded','dead')", name="job_state"),
        CheckConstraint("max_deliveries BETWEEN 1 AND 3", name="job_max_deliveries"),
        CheckConstraint("delivery_count BETWEEN 0 AND max_deliveries", name="job_delivery_count"),
        CheckConstraint(
            "(state = 'leased' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR (state <> 'leased' AND lease_owner IS NULL "
            "AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="job_lease_shape",
        ),
        CheckConstraint(
            "(state IN ('succeeded','dead')) = (finished_at IS NOT NULL)", name="job_terminal_time"
        ),
        Index("ix_jobs_pending", "state", "available_at", "created_at"),
        Index("ix_jobs_expired", "state", "lease_expires_at"),
        Index("ix_jobs_subject", "subject_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    # The only M1 subject is an execution; later kinds require a reviewed migration.
    subject_id: Mapped[UUID] = mapped_column(ForeignKey("executions.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String(16))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[UUID | None]
    lease_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_count: Mapped[int] = mapped_column(Integer)
    max_deliveries: Mapped[int] = mapped_column(Integer)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
