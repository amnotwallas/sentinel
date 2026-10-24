from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
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
        CheckConstraint(
            "result_contract_version BETWEEN 0 AND 1",
            name="execution_result_contract_version",
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
        UniqueConstraint(
            "id",
            "result_contract_version",
            name="uq_executions_identity_contract_version",
        ),
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
    result_contract_version: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
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
            "result_contract_version BETWEEN 0 AND 1",
            name="execution_item_result_contract_version",
        ),
        CheckConstraint(
            "(result_contract_version = 0 AND baseline_activation_id IS NULL "
            "AND baseline_id IS NULL)"
            " OR (result_contract_version = 1 AND ((baseline_activation_id IS NULL "
            "AND baseline_id IS NULL)"
            " OR (baseline_activation_id IS NOT NULL AND baseline_id IS NOT NULL)))",
            name="execution_item_baseline_pin_shape",
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
            ["execution_id", "result_contract_version"],
            ["executions.id", "executions.result_contract_version"],
            ondelete="RESTRICT",
            name="fk_execution_items_execution_contract_version",
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
        ForeignKeyConstraint(
            ["baseline_activation_id", "baseline_id"],
            ["baseline_activations.id", "baseline_activations.baseline_id"],
            ondelete="RESTRICT",
            name="fk_execution_items_baseline_pin",
        ),
        UniqueConstraint("execution_id", "ordinal", name="uq_execution_items_execution_ordinal"),
        UniqueConstraint("execution_id", "test_case_id", name="uq_execution_items_execution_case"),
        UniqueConstraint(
            "id", "execution_id", "project_id", name="uq_execution_items_identity_scope"
        ),
        UniqueConstraint(
            "id",
            "result_contract_version",
            name="uq_execution_items_identity_contract_version",
        ),
        Index("ix_execution_items_execution_order", "execution_id", "ordinal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[UUID]
    ordinal: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[UUID]
    test_case_id: Mapped[UUID]
    test_case_revision_id: Mapped[UUID]
    test_case_revision_version: Mapped[int] = mapped_column(Integer)
    result_contract_version: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    baseline_activation_id: Mapped[UUID | None]
    baseline_id: Mapped[UUID | None]
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
            "result_contract_version BETWEEN 0 AND 1",
            name="test_attempt_result_contract_version",
        ),
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
        CheckConstraint(
            "(result_contract_version = 0 AND verdict IS NULL AND evaluation_error_code IS NULL)"
            " OR (result_contract_version = 1 AND ((state = 'evaluated' AND verdict IS NOT NULL"
            " AND evaluation_error_code IS NULL AND response_recorded_at IS NOT NULL"
            " AND dispatch_certainty = 'response_received'"
            " AND transport_outcome IN ('response_received','response_limit_exceeded'))"
            " OR (state = 'failed' AND verdict IS NULL AND evaluation_error_code IS NULL)"
            " OR (state = 'failed' AND verdict = 'inconclusive'"
            " AND evaluation_error_code = 'platform_evaluation_failure'"
            " AND dispatch_certainty = 'response_received'"
            " AND transport_outcome IN ('response_received','response_limit_exceeded'))"
            " OR (state NOT IN ('evaluated','failed') AND verdict IS NULL"
            " AND evaluation_error_code IS NULL)))",
            name="test_attempt_evaluation_shape",
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('passed','functional_regression',"
            "'performance_warning','observed_change','inconclusive','baseline_required',"
            "'not_evaluated')",
            name="test_attempt_verdict",
        ),
        CheckConstraint(
            "evaluation_error_code IS NULL OR evaluation_error_code = "
            "'platform_evaluation_failure'",
            name="test_attempt_evaluation_error",
        ),
        ForeignKeyConstraint(
            ["execution_item_id", "result_contract_version"],
            ["execution_items.id", "execution_items.result_contract_version"],
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
        UniqueConstraint("id", "execution_item_id", name="uq_test_attempts_identity_item"),
        UniqueConstraint("replay_successor_id", name="uq_test_attempts_replay_successor"),
        Index("ix_test_attempts_item_state", "execution_item_id", "state", "sequence"),
        Index(
            "ix_test_attempts_dispatching", "state", "dispatch_certainty", "dispatch_recorded_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    execution_item_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    result_contract_version: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
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
    verdict: Mapped[str | None] = mapped_column(String(32))
    evaluation_error_code: Mapped[str | None] = mapped_column(String(64))


class BaselineComparisonRow(Base):
    __tablename__ = "baseline_comparisons"
    __table_args__ = (
        CheckConstraint(
            "state IN ('not_requested','missing','incompatible','compatible')",
            name="baseline_comparison_state",
        ),
        CheckConstraint(
            "(state IN ('not_requested','missing') AND baseline_activation_id IS NULL"
            " AND baseline_id IS NULL AND baseline_version IS NULL"
            " AND policy_fingerprint IS NULL AND checked_at IS NOT NULL)"
            " OR (state IN ('incompatible','compatible') AND baseline_activation_id IS NOT NULL"
            " AND baseline_id IS NOT NULL AND baseline_version >= 1"
            " AND policy_fingerprint IS NOT NULL AND checked_at IS NOT NULL)",
            name="baseline_comparison_reference_shape",
        ),
        CheckConstraint(
            "policy_fingerprint IS NULL OR length(policy_fingerprint) = 64",
            name="baseline_comparison_policy_fingerprint",
        ),
        ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempts.id"],
            ondelete="CASCADE",
            name="fk_baseline_comparisons_attempt",
        ),
        ForeignKeyConstraint(
            ["baseline_activation_id", "baseline_id"],
            ["baseline_activations.id", "baseline_activations.baseline_id"],
            ondelete="RESTRICT",
            name="fk_baseline_comparisons_activation_baseline",
        ),
        Index("ix_baseline_comparisons_baseline", "baseline_id", "checked_at", "attempt_id"),
    )

    attempt_id: Mapped[UUID] = mapped_column(primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    baseline_activation_id: Mapped[UUID | None]
    baseline_id: Mapped[UUID | None]
    baseline_version: Mapped[int | None] = mapped_column(Integer)
    policy_fingerprint: Mapped[str | None] = mapped_column(String(64))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvaluationRow(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint("ordinal BETWEEN 0 AND 256", name="evaluation_ordinal"),
        CheckConstraint(
            "kind IN ('assertion','baseline_selector','performance')",
            name="evaluation_kind",
        ),
        CheckConstraint(
            "(kind = 'performance' AND rule_id IS NULL) OR"
            " (kind <> 'performance' AND rule_id IS NOT NULL)",
            name="evaluation_rule_shape",
        ),
        CheckConstraint(
            "severity IN ('required','advisory')",
            name="evaluation_severity",
        ),
        CheckConstraint(
            "kind <> 'performance' OR severity = 'advisory'",
            name="evaluation_performance_severity",
        ),
        CheckConstraint(
            "outcome IN ('passed','failed','unevaluable','not_evaluated')",
            name="evaluation_outcome",
        ),
        CheckConstraint(
            "message_code IN ('assertion_passed','selected_value_match',"
            "'duration_within_threshold','status_mismatch','header_missing',"
            "'header_mismatch','json_missing','json_unexpected','json_type_mismatch',"
            "'json_value_mismatch','text_mismatch','invalid_json',"
            "'selected_value_mismatch','normalizer_input_invalid','baseline_missing',"
            "'baseline_incompatible','content_missing','content_expired',"
            "'content_truncated','content_redacted','duration_exceeded','not_evaluated')",
            name="evaluation_message_code",
        ),
        CheckConstraint(
            "expected IS NULL OR octet_length(expected::text) <= 4096",
            name="evaluation_expected_bound",
        ),
        CheckConstraint(
            "actual IS NULL OR octet_length(actual::text) <= 4096",
            name="evaluation_actual_bound",
        ),
        ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempts.id"],
            ondelete="CASCADE",
            name="fk_evaluations_attempt",
        ),
        UniqueConstraint("attempt_id", "ordinal", name="uq_evaluations_attempt_ordinal"),
        Index("ix_evaluations_attempt_order", "attempt_id", "ordinal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    attempt_id: Mapped[UUID]
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    rule_id: Mapped[UUID | None]
    severity: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(16))
    message_code: Mapped[str] = mapped_column(String(32))
    expected: Mapped[object | None] = mapped_column(JSONB)
    actual: Mapped[object | None] = mapped_column(JSONB)
    evidence_omitted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BaselineRow(Base):
    __tablename__ = "baselines"
    __table_args__ = (
        CheckConstraint("version >= 1", name="baseline_version"),
        CheckConstraint(
            "source_attempt_verdict IN ('passed','functional_regression',"
            "'performance_warning','observed_change','inconclusive','baseline_required',"
            "'not_evaluated')",
            name="baseline_source_verdict",
        ),
        CheckConstraint(
            "length(policy_fingerprint) = 64",
            name="baseline_policy_fingerprint",
        ),
        CheckConstraint(
            "selected_values_schema_version = 1",
            name="baseline_selected_values_schema_version",
        ),
        CheckConstraint(
            "jsonb_typeof(selected_values) = 'object'"
            " AND selected_values ? 'schema_version'"
            " AND (selected_values ->> 'schema_version')::integer = 1"
            " AND jsonb_typeof(selected_values -> 'values') = 'array'"
            " AND jsonb_array_length(selected_values -> 'values') <= 128",
            name="baseline_selected_values_shape",
        ),
        CheckConstraint(
            "reason IS NULL OR (octet_length(reason) BETWEEN 1 AND 500"
            " AND reason !~ '[\\x00-\\x1F\\x7F]')",
            name="baseline_reason",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="RESTRICT",
            name="fk_baselines_project",
        ),
        ForeignKeyConstraint(
            ["test_case_id", "project_id"],
            ["test_cases.id", "test_cases.project_id"],
            ondelete="RESTRICT",
            name="fk_baselines_test_case_project",
        ),
        ForeignKeyConstraint(
            ["environment_id", "project_id"],
            ["environments.id", "environments.project_id"],
            ondelete="RESTRICT",
            name="fk_baselines_environment_project",
        ),
        ForeignKeyConstraint(
            ["source_test_case_revision_id", "test_case_id"],
            ["test_case_revisions.id", "test_case_revisions.test_case_id"],
            ondelete="RESTRICT",
            name="fk_baselines_source_revision",
        ),
        UniqueConstraint(
            "test_case_id", "environment_id", "version", name="uq_baselines_scope_version"
        ),
        UniqueConstraint(
            "id",
            "test_case_id",
            "environment_id",
            "project_id",
            name="uq_baselines_identity_scope",
        ),
        Index(
            "ix_baselines_history",
            "test_case_id",
            "environment_id",
            "version",
            "id",
        ),
        Index(
            "uq_baselines_source_attempt",
            "source_attempt_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    test_case_id: Mapped[UUID]
    environment_id: Mapped[UUID]
    project_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer)
    source_attempt_id: Mapped[UUID]
    source_execution_id: Mapped[UUID] = mapped_column()
    source_test_case_revision_id: Mapped[UUID]
    source_attempt_verdict: Mapped[str] = mapped_column(String(32))
    source_finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    policy_fingerprint: Mapped[str] = mapped_column(String(64))
    selected_values_schema_version: Mapped[int] = mapped_column(SmallInteger)
    selected_values: Mapped[dict[str, object]] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BaselineActivationRow(Base):
    __tablename__ = "baseline_activations"
    __table_args__ = (
        CheckConstraint(
            "deactivated_at IS NULL OR deactivated_at >= activated_at",
            name="baseline_activation_time_order",
        ),
        CheckConstraint(
            "reason IS NULL OR (octet_length(reason) BETWEEN 1 AND 500"
            " AND reason !~ '[\\x00-\\x1F\\x7F]')",
            name="baseline_activation_reason",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="RESTRICT",
            name="fk_baseline_activations_project",
        ),
        ForeignKeyConstraint(
            ["test_case_id", "project_id"],
            ["test_cases.id", "test_cases.project_id"],
            ondelete="RESTRICT",
            name="fk_baseline_activations_test_case_project",
        ),
        ForeignKeyConstraint(
            ["environment_id", "project_id"],
            ["environments.id", "environments.project_id"],
            ondelete="RESTRICT",
            name="fk_baseline_activations_environment_project",
        ),
        ForeignKeyConstraint(
            ["baseline_id", "test_case_id", "environment_id", "project_id"],
            [
                "baselines.id",
                "baselines.test_case_id",
                "baselines.environment_id",
                "baselines.project_id",
            ],
            ondelete="RESTRICT",
            name="fk_baseline_activations_baseline_scope",
        ),
        UniqueConstraint("id", "baseline_id", name="uq_baseline_activations_identity_baseline"),
        Index(
            "ix_baseline_activations_history",
            "test_case_id",
            "environment_id",
            "baseline_id",
            "activated_at",
            "id",
        ),
        Index(
            "uq_baseline_activations_current",
            "test_case_id",
            "environment_id",
            unique=True,
            postgresql_where=text("deactivated_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    test_case_id: Mapped[UUID]
    environment_id: Mapped[UUID]
    project_id: Mapped[UUID]
    baseline_id: Mapped[UUID]
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(500))


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


class TraceReferenceRow(Base):
    __tablename__ = "trace_references"
    __table_args__ = (
        CheckConstraint("relation IN ('primary','linked')", name="trace_reference_relation"),
        CheckConstraint(
            "trace_id ~ '^[0-9a-f]{32}$' AND trace_id !~ '^0+$'",
            name="trace_reference_trace_id",
        ),
        CheckConstraint(
            "span_id IS NULL OR (span_id ~ '^[0-9a-f]{16}$' AND span_id !~ '^0+$')",
            name="trace_reference_span_id",
        ),
        CheckConstraint(
            "(relation = 'primary' AND span_id IS NOT NULL "
            "AND correlation_source = 'sentinel_context') OR "
            "(relation = 'linked' AND correlation_source = 'baggage_attribute_search')",
            name="trace_reference_relation_shape",
        ),
        CheckConstraint(
            "status IN ('pending','missing','available','partial','tempo_unavailable','expired')",
            name="trace_reference_status",
        ),
        CheckConstraint(
            "lookup_attempt_count BETWEEN 0 AND 7", name="trace_reference_lookup_attempt_count"
        ),
        CheckConstraint(
            "last_error_code IS NULL OR last_error_code IN ('not_found','unavailable','timeout',"
            "'bad_response','oversized_response','unsupported','transport_error','invalid_trace',"
            "'correlation_delivery_exhausted')",
            name="trace_reference_error_code",
        ),
        CheckConstraint(
            "evidence_schema_version = 1 AND (evidence_json IS NULL OR "
            "(jsonb_typeof(evidence_json) = 'object' AND evidence_json ? 'schema_version' "
            "AND evidence_json ->> 'schema_version' = '1' "
            "AND (evidence_json - ARRAY['schema_version','primary_span_found',"
            "'trace_span_count','error_span_count','services','deployments',"
            "'linked_match_count','context_continuity','comparison_anchor']) = '{}'::jsonb "
            "AND octet_length(evidence_json::text) <= 65536))",
            name="trace_reference_evidence_shape",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "execution_item_id"],
            ["test_attempts.id", "test_attempts.execution_item_id"],
            ondelete="CASCADE",
            name="fk_trace_references_attempt_item",
        ),
        ForeignKeyConstraint(
            ["execution_item_id", "execution_id", "project_id"],
            ["execution_items.id", "execution_items.execution_id", "execution_items.project_id"],
            ondelete="CASCADE",
            name="fk_trace_references_item_scope",
        ),
        ForeignKeyConstraint(
            ["execution_id", "project_id"],
            ["executions.id", "executions.project_id"],
            ondelete="CASCADE",
            name="fk_trace_references_execution_scope",
        ),
        UniqueConstraint("id", "execution_id", name="uq_trace_references_identity_execution"),
        Index("ix_trace_references_attempt", "attempt_id", "relation", "created_at", "id"),
        Index("ix_trace_references_due", "status", "deadline_at", "updated_at"),
        Index("ix_trace_references_trace", "trace_id", "created_at"),
        Index(
            "uq_trace_references_primary_attempt",
            "attempt_id",
            unique=True,
            postgresql_where=text("relation = 'primary'"),
        ),
        Index(
            "uq_trace_references_linked_identity",
            "attempt_id",
            "relation",
            "trace_id",
            unique=True,
            postgresql_where=text("relation = 'linked'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    attempt_id: Mapped[UUID]
    execution_item_id: Mapped[UUID]
    execution_id: Mapped[UUID]
    project_id: Mapped[UUID]
    relation: Mapped[str] = mapped_column(String(16))
    trace_id: Mapped[str] = mapped_column(String(32))
    span_id: Mapped[str | None] = mapped_column(String(16))
    correlation_source: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    first_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lookup_attempt_count: Mapped[int] = mapped_column(Integer)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    evidence_schema_version: Mapped[int] = mapped_column(SmallInteger)
    evidence_json: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
        CheckConstraint(
            "(kind = 'correlate_trace' AND trace_reference_id IS NOT NULL) OR "
            "(kind <> 'correlate_trace' AND trace_reference_id IS NULL)",
            name="job_trace_reference_shape",
        ),
        ForeignKeyConstraint(
            ["trace_reference_id", "subject_id"],
            ["trace_references.id", "trace_references.execution_id"],
            ondelete="CASCADE",
            name="fk_jobs_trace_reference_execution",
        ),
        UniqueConstraint("trace_reference_id", name="uq_jobs_trace_reference"),
        Index("ix_jobs_pending", "state", "available_at", "created_at"),
        Index("ix_jobs_expired", "state", "lease_expires_at"),
        Index("ix_jobs_subject", "subject_id"),
        Index("ix_jobs_trace_reference", "trace_reference_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    # The only M1 subject is an execution; later kinds require a reviewed migration.
    subject_id: Mapped[UUID] = mapped_column(ForeignKey("executions.id", ondelete="RESTRICT"))
    trace_reference_id: Mapped[UUID | None]
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
