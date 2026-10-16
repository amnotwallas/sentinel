"""Enforce environment active-revision ownership.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_environments_active_revision", "environments", type_="foreignkey")
    op.create_unique_constraint(
        "uq_environment_revisions_identity_owner",
        "environment_revisions",
        ["id", "environment_id"],
    )
    op.create_foreign_key(
        "fk_environments_active_revision",
        "environments",
        "environment_revisions",
        ["active_revision_id", "id"],
        ["id", "environment_id"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("fk_environments_active_revision", "environments", type_="foreignkey")
    op.drop_constraint(
        "uq_environment_revisions_identity_owner",
        "environment_revisions",
        type_="unique",
    )
    op.create_foreign_key(
        "fk_environments_active_revision",
        "environments",
        "environment_revisions",
        ["active_revision_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )
