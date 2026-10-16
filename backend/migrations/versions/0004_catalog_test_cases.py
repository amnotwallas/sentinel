"""Add immutable test case catalog revisions.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("active_revision_id", sa.Uuid(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state_version BETWEEN 1 AND 2147483647", name="test_case_state_version"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "test_case_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("unsafe_replay_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unsafe_replay_acknowledgement", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version BETWEEN 1 AND 2147483647", name="test_case_revision_version"),
        sa.CheckConstraint(
            "(unsafe_replay_acknowledgement IS NULL AND unsafe_replay_acknowledged_at IS NULL) "
            "OR (unsafe_replay_acknowledgement = 'duplicate_effects_possible' "
            "AND unsafe_replay_acknowledged_at IS NOT NULL)",
            name="test_case_replay_ack_shape",
        ),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "test_case_id", name="uq_test_case_revisions_identity_owner"),
    )
    op.create_index("ix_test_cases_project_list", "test_cases", ["project_id", "created_at", "id"])
    op.create_index(
        "uq_test_case_revisions_version",
        "test_case_revisions",
        ["test_case_id", "version"],
        unique=True,
    )
    op.create_index(
        "ix_test_case_revisions_history",
        "test_case_revisions",
        ["test_case_id", "version", "id"],
    )
    op.create_foreign_key(
        "fk_test_cases_active_revision",
        "test_cases",
        "test_case_revisions",
        ["active_revision_id", "id"],
        ["id", "test_case_id"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("fk_test_cases_active_revision", "test_cases", type_="foreignkey")
    op.drop_index("ix_test_case_revisions_history", table_name="test_case_revisions")
    op.drop_index("uq_test_case_revisions_version", table_name="test_case_revisions")
    op.drop_index("ix_test_cases_project_list", table_name="test_cases")
    op.drop_table("test_case_revisions")
    op.drop_table("test_cases")
