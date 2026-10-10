"""Initial durable work schema. Downgrade deletes probe/queue data; back up first."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("verdict", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed')", name="execution_status"
        ),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict = 'not_evaluated'", name="execution_verdict"
        ),
        sa.CheckConstraint(
            "(status IN ('completed','failed')) = (finished_at IS NOT NULL)",
            name="execution_terminal_time",
        ),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column(
            "subject_id",
            sa.Uuid(),
            sa.ForeignKey("executions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Uuid()),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_count", sa.Integer(), nullable=False),
        sa.Column("max_deliveries", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('pending','leased','succeeded','dead')", name="job_state"),
        sa.CheckConstraint("max_deliveries BETWEEN 1 AND 3", name="job_max_deliveries"),
        sa.CheckConstraint(
            "delivery_count BETWEEN 0 AND max_deliveries", name="job_delivery_count"
        ),
        sa.CheckConstraint(
            "(state = 'leased' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR (state <> 'leased' AND lease_owner IS NULL "
            "AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="job_lease_shape",
        ),
        sa.CheckConstraint(
            "(state IN ('succeeded','dead')) = (finished_at IS NOT NULL)", name="job_terminal_time"
        ),
    )
    op.create_index("ix_jobs_pending", "jobs", ["state", "available_at", "created_at"])
    op.create_index("ix_jobs_expired", "jobs", ["state", "lease_expires_at"])
    op.create_index("ix_jobs_subject", "jobs", ["subject_id"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("executions")
