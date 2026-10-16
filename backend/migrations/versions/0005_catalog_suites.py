"""Add immutable ordered suite catalog revisions.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_test_cases_identity_project",
        "test_cases",
        ["id", "project_id"],
    )
    op.create_unique_constraint(
        "uq_test_case_revisions_identity_owner_version",
        "test_case_revisions",
        ["id", "test_case_id", "version"],
    )
    op.create_table(
        "suites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("active_revision_id", sa.Uuid(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state_version BETWEEN 1 AND 2147483647", name="suite_state_version"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", name="uq_suites_identity_project"),
    )
    op.create_table(
        "suite_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version BETWEEN 1 AND 2147483647", name="suite_revision_version"),
        sa.ForeignKeyConstraint(
            ["suite_id", "project_id"],
            ["suites.id", "suites.project_id"],
            ondelete="RESTRICT",
            name="fk_suite_revisions_suite_project",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "suite_id", name="uq_suite_revisions_identity_owner"),
        sa.UniqueConstraint("id", "project_id", name="uq_suite_revisions_identity_project"),
    )
    op.create_table(
        "suite_revision_items",
        sa.Column("suite_revision_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_revision_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_revision_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 99", name="suite_revision_item_ordinal"),
        sa.CheckConstraint(
            "test_case_revision_version BETWEEN 1 AND 2147483647",
            name="suite_revision_item_version",
        ),
        sa.ForeignKeyConstraint(
            ["suite_revision_id", "project_id"],
            ["suite_revisions.id", "suite_revisions.project_id"],
            ondelete="RESTRICT",
            name="fk_suite_revision_items_revision_project",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id", "project_id"],
            ["test_cases.id", "test_cases.project_id"],
            ondelete="RESTRICT",
            name="fk_suite_revision_items_test_case_project",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_revision_id", "test_case_id", "test_case_revision_version"],
            [
                "test_case_revisions.id",
                "test_case_revisions.test_case_id",
                "test_case_revisions.version",
            ],
            ondelete="RESTRICT",
            name="fk_suite_revision_items_test_case_revision_version",
        ),
        sa.PrimaryKeyConstraint("suite_revision_id", "ordinal"),
        sa.UniqueConstraint(
            "suite_revision_id", "test_case_id", name="uq_suite_revision_items_case"
        ),
    )
    op.create_index("ix_suites_project_list", "suites", ["project_id", "created_at", "id"])
    op.create_index(
        "uq_suite_revisions_version",
        "suite_revisions",
        ["suite_id", "version"],
        unique=True,
    )
    op.create_index("ix_suite_revisions_history", "suite_revisions", ["suite_id", "version", "id"])
    op.create_index(
        "ix_suite_revision_items_revision_order",
        "suite_revision_items",
        ["suite_revision_id", "ordinal"],
    )
    op.create_foreign_key(
        "fk_suites_active_revision",
        "suites",
        "suite_revisions",
        ["active_revision_id", "id"],
        ["id", "suite_id"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("fk_suites_active_revision", "suites", type_="foreignkey")
    op.drop_index("ix_suite_revision_items_revision_order", table_name="suite_revision_items")
    op.drop_index("ix_suite_revisions_history", table_name="suite_revisions")
    op.drop_index("uq_suite_revisions_version", table_name="suite_revisions")
    op.drop_index("ix_suites_project_list", table_name="suites")
    op.drop_table("suite_revision_items")
    op.drop_table("suite_revisions")
    op.drop_table("suites")
    op.drop_constraint(
        "uq_test_case_revisions_identity_owner_version",
        "test_case_revisions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_test_cases_identity_project",
        "test_cases",
        type_="unique",
    )
