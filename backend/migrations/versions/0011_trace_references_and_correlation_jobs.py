"""Persist safe trace references and durable correlation jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Composite parent keys make project/execution ownership database-enforced.
    op.create_unique_constraint(
        "uq_execution_items_identity_scope", "execution_items", ["id", "execution_id", "project_id"]
    )
    op.create_unique_constraint(
        "uq_test_attempts_identity_item", "test_attempts", ["id", "execution_item_id"]
    )

    op.create_table(
        "trace_references",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("execution_item_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("relation", sa.String(16), nullable=False),
        sa.Column("trace_id", sa.String(32), nullable=False),
        sa.Column("span_id", sa.String(16)),
        sa.Column("correlation_source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("first_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lookup_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("evidence_schema_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("evidence_json", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("relation IN ('primary','linked')", name="trace_reference_relation"),
        sa.CheckConstraint(
            "trace_id ~ '^[0-9a-f]{32}$' AND trace_id !~ '^0+$'",
            name="trace_reference_trace_id",
        ),
        sa.CheckConstraint(
            "span_id IS NULL OR (span_id ~ '^[0-9a-f]{16}$' AND span_id !~ '^0+$')",
            name="trace_reference_span_id",
        ),
        sa.CheckConstraint(
            "(relation = 'primary' AND span_id IS NOT NULL "
            "AND correlation_source = 'sentinel_context') OR "
            "(relation = 'linked' AND correlation_source = 'baggage_attribute_search')",
            name="trace_reference_relation_shape",
        ),
        sa.CheckConstraint(
            "status IN ('pending','missing','available','partial','tempo_unavailable','expired')",
            name="trace_reference_status",
        ),
        sa.CheckConstraint(
            "lookup_attempt_count BETWEEN 0 AND 7", name="trace_reference_lookup_attempt_count"
        ),
        sa.CheckConstraint(
            "last_error_code IS NULL OR last_error_code IN ('not_found','unavailable','timeout',"
            "'bad_response','oversized_response','unsupported','transport_error','invalid_trace',"
            "'correlation_delivery_exhausted')",
            name="trace_reference_error_code",
        ),
        sa.CheckConstraint(
            "evidence_schema_version = 1 AND (evidence_json IS NULL OR "
            "(jsonb_typeof(evidence_json) = 'object' AND evidence_json ? 'schema_version' "
            "AND evidence_json ->> 'schema_version' = '1' "
            "AND (evidence_json - ARRAY['schema_version','primary_span_found',"
            "'trace_span_count','error_span_count','services','deployments',"
            "'linked_match_count','context_continuity','comparison_anchor']) = '{}'::jsonb "
            "AND octet_length(evidence_json::text) <= 65536))",
            name="trace_reference_evidence_shape",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "execution_item_id"],
            ["test_attempts.id", "test_attempts.execution_item_id"],
            ondelete="CASCADE",
            name="fk_trace_references_attempt_item",
        ),
        sa.ForeignKeyConstraint(
            ["execution_item_id", "execution_id", "project_id"],
            ["execution_items.id", "execution_items.execution_id", "execution_items.project_id"],
            ondelete="CASCADE",
            name="fk_trace_references_item_scope",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "project_id"],
            ["executions.id", "executions.project_id"],
            ondelete="CASCADE",
            name="fk_trace_references_execution_scope",
        ),
        sa.UniqueConstraint("id", "execution_id", name="uq_trace_references_identity_execution"),
    )
    op.create_index(
        "ix_trace_references_attempt",
        "trace_references",
        ["attempt_id", "relation", "created_at", "id"],
    )
    op.create_index(
        "ix_trace_references_due", "trace_references", ["status", "deadline_at", "updated_at"]
    )
    op.create_index("ix_trace_references_trace", "trace_references", ["trace_id", "created_at"])
    op.create_index(
        "uq_trace_references_primary_attempt",
        "trace_references",
        ["attempt_id"],
        unique=True,
        postgresql_where=sa.text("relation = 'primary'"),
    )
    op.create_index(
        "uq_trace_references_linked_identity",
        "trace_references",
        ["attempt_id", "relation", "trace_id"],
        unique=True,
        postgresql_where=sa.text("relation = 'linked'"),
    )

    op.add_column("jobs", sa.Column("trace_reference_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_jobs_trace_reference_execution",
        "jobs",
        "trace_references",
        ["trace_reference_id", "subject_id"],
        ["id", "execution_id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "job_trace_reference_shape",
        "jobs",
        "(kind = 'correlate_trace' AND trace_reference_id IS NOT NULL) OR "
        "(kind <> 'correlate_trace' AND trace_reference_id IS NULL)",
    )
    op.create_unique_constraint("uq_jobs_trace_reference", "jobs", ["trace_reference_id"])
    op.create_index("ix_jobs_trace_reference", "jobs", ["trace_reference_id"])

    op.execute(
        """
        CREATE FUNCTION sentinel_validate_correlation_job() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.kind = 'correlate_trace' AND NOT EXISTS (
            SELECT 1 FROM trace_references ref
            WHERE ref.id = NEW.trace_reference_id
              AND ref.execution_id = NEW.subject_id
              AND ref.relation = 'primary'
          ) THEN
            RAISE EXCEPTION 'correlation job requires a primary trace reference';
          END IF;
          RETURN NEW;
        END;
        $$;
        CREATE CONSTRAINT TRIGGER correlation_job_primary_reference
        AFTER INSERT OR UPDATE ON jobs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION sentinel_validate_correlation_job();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS correlation_job_primary_reference ON jobs; "
        "DROP FUNCTION IF EXISTS sentinel_validate_correlation_job();"
    )
    # Correlation jobs cannot be represented by the pre-M5 jobs schema.
    op.execute("DELETE FROM jobs WHERE kind = 'correlate_trace'")
    op.drop_index("ix_jobs_trace_reference", table_name="jobs")
    op.drop_constraint("uq_jobs_trace_reference", "jobs", type_="unique")
    op.drop_constraint("job_trace_reference_shape", "jobs", type_="check")
    op.drop_constraint("fk_jobs_trace_reference_execution", "jobs", type_="foreignkey")
    op.drop_column("jobs", "trace_reference_id")
    op.drop_index("uq_trace_references_linked_identity", table_name="trace_references")
    op.drop_index("uq_trace_references_primary_attempt", table_name="trace_references")
    op.drop_index("ix_trace_references_trace", table_name="trace_references")
    op.drop_index("ix_trace_references_due", table_name="trace_references")
    op.drop_index("ix_trace_references_attempt", table_name="trace_references")
    op.drop_table("trace_references")
    op.drop_constraint("uq_test_attempts_identity_item", "test_attempts", type_="unique")
    op.drop_constraint("uq_execution_items_identity_scope", "execution_items", type_="unique")
