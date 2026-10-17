"""Add atomic execution materialization and idempotency records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("execution_verdict", "executions", type_="check")
    op.create_check_constraint(
        "execution_verdict",
        "executions",
        "verdict IS NULL OR verdict IN ('passed','functional_regression',"
        "'performance_warning','observed_change','inconclusive','baseline_required',"
        "'not_evaluated')",
    )
    op.create_unique_constraint(
        "uq_environments_identity_project", "environments", ["id", "project_id"]
    )

    for column in (
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("environment_id", sa.Uuid(), nullable=True),
        sa.Column("environment_revision_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(16), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("source_revision_id", sa.Uuid(), nullable=True),
    ):
        op.add_column("executions", column)
    op.create_check_constraint(
        "execution_materialization_shape",
        "executions",
        "(project_id IS NULL AND environment_id IS NULL AND environment_revision_id IS NULL "
        "AND source_type IS NULL AND source_id IS NULL AND source_revision_id IS NULL) OR "
        "(project_id IS NOT NULL AND environment_id IS NOT NULL "
        "AND environment_revision_id IS NOT NULL AND source_type IS NOT NULL "
        "AND source_id IS NOT NULL AND source_revision_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "execution_source_type",
        "executions",
        "source_type IS NULL OR source_type IN ('test_case','suite')",
    )
    op.create_unique_constraint(
        "uq_executions_identity_project", "executions", ["id", "project_id"]
    )
    op.create_index(
        "ix_executions_project_created", "executions", ["project_id", "created_at", "id"]
    )
    op.create_index(
        "ix_executions_source", "executions", ["source_type", "source_id", "created_at", "id"]
    )
    op.create_foreign_key(
        "fk_executions_environment_project",
        "executions",
        "environments",
        ["environment_id", "project_id"],
        ["id", "project_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_executions_environment_revision",
        "executions",
        "environment_revisions",
        ["environment_revision_id", "environment_id"],
        ["id", "environment_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "execution_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_revision_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_revision_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("verdict", sa.String(32)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 99", name="execution_item_ordinal"),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','indeterminate','failed','skipped')",
            name="execution_item_status",
        ),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('passed','functional_regression',"
            "'performance_warning','observed_change','inconclusive','baseline_required',"
            "'not_evaluated')",
            name="execution_item_verdict",
        ),
        sa.CheckConstraint(
            "test_case_revision_version BETWEEN 1 AND 2147483647",
            name="execution_item_revision_version",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
            "(status <> 'pending')",
            name="execution_item_pending_time",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "project_id"],
            ["executions.id", "executions.project_id"],
            ondelete="RESTRICT",
            name="fk_execution_items_execution_project",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id", "project_id"],
            ["test_cases.id", "test_cases.project_id"],
            ondelete="RESTRICT",
            name="fk_execution_items_test_case_project",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_revision_id", "test_case_id", "test_case_revision_version"],
            [
                "test_case_revisions.id",
                "test_case_revisions.test_case_id",
                "test_case_revisions.version",
            ],
            ondelete="RESTRICT",
            name="fk_execution_items_test_case_revision",
        ),
        sa.UniqueConstraint("execution_id", "ordinal", name="uq_execution_items_execution_ordinal"),
        sa.UniqueConstraint(
            "execution_id", "test_case_id", name="uq_execution_items_execution_case"
        ),
    )
    op.create_index(
        "ix_execution_items_execution_order", "execution_items", ["execution_id", "ordinal"]
    )

    op.create_table(
        "execution_idempotency",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(key_hash) = 64", name="execution_idempotency_key_hash"),
        sa.CheckConstraint("length(request_hash) = 64", name="execution_idempotency_request_hash"),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["executions.id"],
            ondelete="RESTRICT",
            name="fk_idempotency_execution",
        ),
        sa.UniqueConstraint("execution_id", "key_hash", name="uq_idempotency_execution_key"),
    )
    op.create_index("ix_execution_idempotency_expiry", "execution_idempotency", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_execution_idempotency_expiry", table_name="execution_idempotency")
    op.drop_table("execution_idempotency")
    op.drop_index("ix_execution_items_execution_order", table_name="execution_items")
    op.drop_table("execution_items")
    op.drop_constraint("fk_executions_environment_revision", "executions", type_="foreignkey")
    op.drop_constraint("fk_executions_environment_project", "executions", type_="foreignkey")
    op.drop_index("ix_executions_source", table_name="executions")
    op.drop_index("ix_executions_project_created", table_name="executions")
    op.drop_constraint("uq_executions_identity_project", "executions", type_="unique")
    op.drop_constraint("execution_source_type", "executions", type_="check")
    op.drop_constraint("execution_materialization_shape", "executions", type_="check")
    op.drop_constraint("execution_verdict", "executions", type_="check")
    # M1 only represented an unevaluated verdict. Preserve downgrade validity
    # by reducing newer terminal verdicts to the M1-compatible value before
    # restoring its narrower constraint. Execution items are dropped above.
    op.execute(
        "UPDATE executions SET verdict = 'not_evaluated' "
        "WHERE verdict IS NOT NULL AND verdict <> 'not_evaluated'"
    )
    op.create_check_constraint(
        "execution_verdict", "executions", "verdict IS NULL OR verdict = 'not_evaluated'"
    )
    for name in (
        "source_revision_id",
        "source_id",
        "source_type",
        "environment_revision_id",
        "environment_id",
        "project_id",
    ):
        op.drop_column("executions", name)
    op.drop_constraint("uq_environments_identity_project", "environments", type_="unique")
