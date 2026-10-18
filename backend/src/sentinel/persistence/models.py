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
        ForeignKeyConstraint(
            ["active_revision_id", "id"],
            ["environment_revisions.id", "environment_revisions.environment_id"],
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            name="fk_environments_active_revision",
        ),
        UniqueConstraint("id", "project_id", name="uq_environments_identity_project"),
        Index("ix_environments_project_list", "project_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    active_revision_id: Mapped[UUID]
    state_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnvironmentRevisionRow(Base):
    __tablename__ = "environment_revisions"
    __table_args__ = (
        CheckConstraint("version BETWEEN 1 AND 2147483647", name="environment_revision_version"),
        UniqueConstraint("id", "environment_id", name="uq_environment_revisions_identity_owner"),
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
    """Execution envelope; nullable catalog pins preserve legacy M1 probe rows."""

    __tablename__ = "executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','failed')", name="execution_status"
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('passed','functional_regression',"
            "'performance_warning','observed_change','inconclusive','baseline_required',"
            "'not_evaluated')",
            name="execution_verdict",
        ),
        CheckConstraint(
            "(status IN ('completed','failed')) = (finished_at IS NOT NULL)",
            name="execution_terminal_time",
        ),
        CheckConstraint(
            "(project_id IS NULL AND environment_id IS NULL AND environment_revision_id IS NULL "
            "AND source_type IS NULL AND source_id IS NULL AND source_revision_id IS NULL) OR "
            "(project_id IS NOT NULL AND environment_id IS NOT NULL "
            "AND environment_revision_id IS NOT NULL AND source_type IS NOT NULL "
            "AND source_id IS NOT NULL AND source_revision_id IS NOT NULL)",
            name="execution_materialization_shape",
        ),
        CheckConstraint(
            "source_type IS NULL OR source_type IN ('test_case','suite')",
            name="execution_source_type",
        ),
        ForeignKeyConstraint(
            ["environment_id", "project_id"],
            ["environments.id", "environments.project_id"],
            ondelete="RESTRICT",
            name="fk_executions_environment_project",
        ),
        ForeignKeyConstraint(
            ["environment_revision_id", "environment_id"],
            ["environment_revisions.id", "environment_revisions.environment_id"],
            ondelete="RESTRICT",
            name="fk_executions_environment_revision",
        ),
        UniqueConstraint("id", "project_id", name="uq_executions_identity_project"),
        Index("ix_executions_project_created", "project_id", "created_at", "id"),
        Index("ix_executions_source", "source_type", "source_id", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID | None] = mapped_column()
    environment_id: Mapped[UUID | None] = mapped_column()
    environment_revision_id: Mapped[UUID | None] = mapped_column()
    source_type: Mapped[str | None] = mapped_column(String(16))
    source_id: Mapped[UUID | None] = mapped_column()
    source_revision_id: Mapped[UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16))
    verdict: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionItemRow(Base):
    __tablename__ = "execution_items"
    __table_args__ = (
        CheckConstraint("ordinal BETWEEN 0 AND 99", name="execution_item_ordinal"),
        CheckConstraint(
            "status IN ('pending','running','completed','indeterminate','failed','skipped')",
            name="execution_item_status",
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('passed','functional_regression',"
            "'performance_warning','observed_change','inconclusive','baseline_required',"
            "'not_evaluated')",
            name="execution_item_verdict",
        ),
        CheckConstraint(
            "test_case_revision_version BETWEEN 1 AND 2147483647",
            name="execution_item_revision_version",
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
            "(status <> 'pending')",
            name="execution_item_pending_time",
        ),
        ForeignKeyConstraint(
            ["execution_id", "project_id"],
            ["executions.id", "executions.project_id"],
            ondelete="RESTRICT",
            name="fk_execution_items_execution_project",
        ),
        ForeignKeyConstraint(
            ["test_case_id", "project_id"],
            ["test_cases.id", "test_cases.project_id"],
            ondelete="RESTRICT",
            name="fk_execution_items_test_case_project",
        ),
        ForeignKeyConstraint(
            ["test_case_revision_id", "test_case_id", "test_case_revision_version"],
            [
                "test_case_revisions.id",
                "test_case_revisions.test_case_id",
                "test_case_revisions.version",
            ],
            ondelete="RESTRICT",
            name="fk_execution_items_test_case_revision",
        ),
        UniqueConstraint("execution_id", "ordinal", name="uq_execution_items_execution_ordinal"),
        UniqueConstraint("execution_id", "test_case_id", name="uq_execution_items_execution_case"),
        Index("ix_execution_items_execution_order", "execution_id", "ordinal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[UUID]
    ordinal: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[UUID]
    test_case_id: Mapped[UUID]
    test_case_revision_id: Mapped[UUID]
    test_case_revision_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    verdict: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TestAttemptRow(Base):
    """Durable attempt checkpoints; request/response secrets never live here."""

    __test__ = False
    __tablename__ = "test_attempts"
    __table_args__ = (
        CheckConstraint("sequence BETWEEN 1 AND 2147483647", name="test_attempt_sequence"),
        CheckConstraint(
            "state IN ('prepared','dispatching','response_received','transport_failed',"
            "'evaluated','replay_scheduled','indeterminate','failed')",
            name="test_attempt_state",
        ),
        CheckConstraint(
            "dispatch_certainty IN ('not_started','not_sent','possibly_sent','response_received')",
            name="test_attempt_dispatch_certainty",
        ),
        CheckConstraint(
            "transport_outcome IS NULL OR transport_outcome IN ('response_received','dns_failure',"
            "'connect_timeout','connection_failure','tls_failure','write_timeout','write_failure',"
            "'read_timeout','read_failure','total_timeout','target_denied','redirect_denied',"
            "'response_limit_exceeded','indeterminate')",
            name="test_attempt_transport_outcome",
        ),
        CheckConstraint(
            "preparation_error_code IS NULL OR preparation_error_code IN ('secret_missing',"
            "'template_variable_missing','target_policy_denied','request_invalid',"
            "'tls_verification_required','infrastructure_failure')",
            name="test_attempt_preparation_error",
        ),
        CheckConstraint(
            "redirect_rejection_code IS NULL OR redirect_rejection_code IN ('method_not_allowed',"
            "'location_missing','location_invalid','scheme_denied','port_denied','target_denied',"
            "'redirect_limit_exceeded')",
            name="test_attempt_redirect_rejection",
        ),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="test_attempt_duration"),
        CheckConstraint(
            "request_fingerprint IS NULL OR length(request_fingerprint) = 64",
            name="test_attempt_fingerprint",
        ),
        CheckConstraint(
            "primary_trace_id IS NULL OR length(primary_trace_id) = 32",
            name="test_attempt_trace_id",
        ),
        CheckConstraint(
            "client_span_id IS NULL OR length(client_span_id) = 16",
            name="test_attempt_span_id",
        ),
        CheckConstraint(
            "((state = 'prepared' AND dispatch_certainty = 'not_started' AND "
            "preparation_error_code IS NULL) OR "
            "(state = 'failed' AND dispatch_certainty = 'not_started' AND "
            "preparation_error_code IS NOT NULL) OR "
            "(state = 'failed' AND dispatch_certainty <> 'not_started' AND "
            "preparation_error_code IS NULL) OR state NOT IN ('prepared','failed'))",
            name="test_attempt_preparation_shape",
        ),
        CheckConstraint(
            "(state IN ('dispatching','response_received','transport_failed','evaluated',"
            "'replay_scheduled','indeterminate') AND request_fingerprint IS NOT NULL "
            "AND primary_trace_id IS NOT NULL AND client_span_id IS NOT NULL "
            "AND dispatch_recorded_at IS NOT NULL) OR "
            "state = 'prepared' OR "
            "(state = 'failed' AND dispatch_certainty = 'not_started') OR "
            "(state = 'failed' AND dispatch_certainty <> 'not_started' "
            "AND request_fingerprint IS NOT NULL AND primary_trace_id IS NOT NULL "
            "AND client_span_id IS NOT NULL AND dispatch_recorded_at IS NOT NULL)",
            name="test_attempt_dispatch_shape",
        ),
        CheckConstraint(
            "(state = 'prepared' AND request_fingerprint IS NULL AND primary_trace_id IS NULL "
            "AND client_span_id IS NULL AND dispatch_recorded_at IS NULL) OR "
            "(state = 'failed' AND dispatch_certainty = 'not_started' "
            "AND request_fingerprint IS NULL AND primary_trace_id IS NULL "
            "AND client_span_id IS NULL AND dispatch_recorded_at IS NULL) OR "
            "(state NOT IN ('prepared','failed') OR dispatch_certainty <> 'not_started')",
            name="test_attempt_pre_dispatch_fields",
        ),
        CheckConstraint(
            "state <> 'response_received' OR (response_recorded_at IS NOT NULL "
            "AND dispatch_certainty = 'response_received' "
            "AND transport_outcome IN ('response_received','response_limit_exceeded'))",
            name="test_attempt_response_shape",
        ),
        CheckConstraint(
            "state <> 'transport_failed' OR (transport_outcome IS NOT NULL "
            "AND transport_outcome <> 'response_received')",
            name="test_attempt_transport_failure_shape",
        ),
        CheckConstraint(
            "(dispatch_certainty = 'not_sent' AND state = 'transport_failed' AND "
            "transport_outcome IN ('dns_failure','connect_timeout','connection_failure',"
            "'tls_failure','target_denied')) OR dispatch_certainty <> 'not_sent'",
            name="test_attempt_not_sent_shape",
        ),
        CheckConstraint(
            "(state = 'dispatching' AND dispatch_certainty = 'possibly_sent') OR "
            "(state = 'response_received' AND dispatch_certainty = 'response_received' "
            "AND transport_outcome IN ('response_received','response_limit_exceeded')) OR "
            "(state = 'transport_failed' AND ((dispatch_certainty = 'not_sent' AND "
            "transport_outcome IN ('dns_failure','connect_timeout','connection_failure',"
            "'tls_failure','target_denied')) OR (dispatch_certainty = 'possibly_sent' AND "
            "transport_outcome IN ('write_timeout','write_failure','read_timeout','read_failure',"
            "'total_timeout','indeterminate')) OR "
            "(dispatch_certainty = 'response_received' AND transport_outcome IN "
            "('redirect_denied','read_timeout','read_failure','dns_failure','connect_timeout',"
            "'connection_failure','tls_failure','target_denied')))) OR "
            "(state IN ('evaluated','replay_scheduled','indeterminate') AND "
            "dispatch_certainty <> 'not_started') OR "
            "(state = 'prepared' AND dispatch_certainty = 'not_started') OR "
            "(state = 'failed')",
            name="test_attempt_outcome_matrix",
        ),
        CheckConstraint(
            "redirect_rejection_code IS NULL OR transport_outcome = 'redirect_denied'",
            name="test_attempt_redirect_code_shape",
        ),
        CheckConstraint(
            "replay_successor_id IS NULL OR replay_successor_id <> id",
            name="test_attempt_replay_not_self",
        ),
        CheckConstraint(
            "state <> 'replay_scheduled' OR replay_successor_id IS NOT NULL",
            name="test_attempt_replay_shape",
        ),
        ForeignKeyConstraint(
            ["execution_item_id"],
            ["execution_items.id"],
            ondelete="RESTRICT",
            name="fk_test_attempts_execution_item",
        ),
        ForeignKeyConstraint(
            ["replay_successor_id"],
            ["test_attempts.id"],
            ondelete="RESTRICT",
            name="fk_test_attempts_replay_successor",
        ),
        UniqueConstraint("execution_item_id", "sequence", name="uq_test_attempts_item_sequence"),
        UniqueConstraint("replay_successor_id", name="uq_test_attempts_replay_successor"),
        Index("ix_test_attempts_item_state", "execution_item_id", "state", "sequence"),
        Index(
            "ix_test_attempts_dispatching", "state", "dispatch_certainty", "dispatch_recorded_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    execution_item_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24))
    dispatch_certainty: Mapped[str] = mapped_column(String(24))
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatch_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    transport_outcome: Mapped[str | None] = mapped_column(String(32))
    preparation_error_code: Mapped[str | None] = mapped_column(String(32))
    redirect_rejection_code: Mapped[str | None] = mapped_column(String(32))
    replay_successor_id: Mapped[UUID | None]
    primary_trace_id: Mapped[str | None] = mapped_column(String(32))
    client_span_id: Mapped[str | None] = mapped_column(String(16))
    included_in_verdict: Mapped[bool] = mapped_column(default=True)


class ResponseArtifactRow(Base):
    """One bounded, already-redacted observation per attempt."""

    __tablename__ = "response_artifacts"
    __table_args__ = (
        CheckConstraint("status_code BETWEEN 100 AND 599", name="response_artifact_status"),
        CheckConstraint(
            "body_kind IS NULL OR body_kind IN ('json','text','bytes')",
            name="response_artifact_body_kind",
        ),
        CheckConstraint("source_bytes_captured >= 0", name="response_artifact_source_bytes"),
        CheckConstraint(
            "(body_kind IS NULL AND body_content IS NULL) OR "
            "(body_kind IS NOT NULL AND body_content IS NOT NULL)",
            name="response_artifact_body_shape",
        ),
        ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempts.id"],
            ondelete="RESTRICT",
            name="fk_response_artifacts_attempt",
        ),
    )

    attempt_id: Mapped[UUID] = mapped_column(primary_key=True)
    status_code: Mapped[int] = mapped_column(Integer)
    headers: Mapped[dict[str, object]] = mapped_column(JSONB)
    body_kind: Mapped[str | None] = mapped_column(String(16))
    body_content: Mapped[object | None] = mapped_column(JSONB)
    source_bytes_captured: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(default=False)
    redaction_unavailable: Mapped[bool] = mapped_column(default=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRecordRow(Base):
    __tablename__ = "execution_idempotency"
    __table_args__ = (
        CheckConstraint("length(key_hash) = 64", name="execution_idempotency_key_hash"),
        CheckConstraint("length(request_hash) = 64", name="execution_idempotency_request_hash"),
        ForeignKeyConstraint(
            ["execution_id"],
            ["executions.id"],
            ondelete="RESTRICT",
            name="fk_idempotency_execution",
        ),
        UniqueConstraint("execution_id", "key_hash", name="uq_idempotency_execution_key"),
        Index("ix_execution_idempotency_expiry", "expires_at"),
    )

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    execution_id: Mapped[UUID]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
