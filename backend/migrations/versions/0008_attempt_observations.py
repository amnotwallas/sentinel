"""Add durable attempts and bounded redacted response artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_item_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("dispatch_certainty", sa.String(24), nullable=False),
        sa.Column("request_fingerprint", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatch_recorded_at", sa.DateTime(timezone=True)),
        sa.Column("response_recorded_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("transport_outcome", sa.String(32)),
        sa.Column("preparation_error_code", sa.String(32)),
        sa.Column("redirect_rejection_code", sa.String(32)),
        sa.Column("replay_successor_id", sa.Uuid()),
        sa.Column("primary_trace_id", sa.String(32)),
        sa.Column("client_span_id", sa.String(16)),
        sa.Column("included_in_verdict", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("sequence BETWEEN 1 AND 2147483647", name="test_attempt_sequence"),
        sa.CheckConstraint(
            "state IN ('prepared','dispatching','response_received','transport_failed',"
            "'evaluated','replay_scheduled','indeterminate','failed')",
            name="test_attempt_state",
        ),
        sa.CheckConstraint(
            "dispatch_certainty IN ('not_started','not_sent','possibly_sent','response_received')",
            name="test_attempt_dispatch_certainty",
        ),
        sa.CheckConstraint(
            "transport_outcome IS NULL OR transport_outcome IN ('response_received','dns_failure',"
            "'connect_timeout','connection_failure','tls_failure','write_timeout','write_failure',"
            "'read_timeout','read_failure','total_timeout','target_denied','redirect_denied',"
            "'response_limit_exceeded','indeterminate')",
            name="test_attempt_transport_outcome",
        ),
        sa.CheckConstraint(
            "preparation_error_code IS NULL OR preparation_error_code IN ('secret_missing',"
            "'template_variable_missing','target_policy_denied','request_invalid',"
            "'tls_verification_required','infrastructure_failure')",
            name="test_attempt_preparation_error",
        ),
        sa.CheckConstraint(
            "redirect_rejection_code IS NULL OR redirect_rejection_code IN ('method_not_allowed',"
            "'location_missing','location_invalid','scheme_denied','port_denied','target_denied',"
            "'redirect_limit_exceeded')",
            name="test_attempt_redirect_rejection",
        ),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="test_attempt_duration"),
        sa.CheckConstraint(
            "request_fingerprint IS NULL OR length(request_fingerprint) = 64",
            name="test_attempt_fingerprint",
        ),
        sa.CheckConstraint(
            "primary_trace_id IS NULL OR length(primary_trace_id) = 32",
            name="test_attempt_trace_id",
        ),
        sa.CheckConstraint(
            "client_span_id IS NULL OR length(client_span_id) = 16",
            name="test_attempt_span_id",
        ),
        sa.CheckConstraint(
            "((state = 'prepared' AND dispatch_certainty = 'not_started' AND "
            "preparation_error_code IS NULL) OR "
            "(state = 'failed' AND dispatch_certainty = 'not_started' AND "
            "preparation_error_code IS NOT NULL) OR "
            "(state = 'failed' AND dispatch_certainty <> 'not_started' AND "
            "preparation_error_code IS NULL) OR state NOT IN ('prepared','failed'))",
            name="test_attempt_preparation_shape",
        ),
        sa.CheckConstraint(
            "(state IN ('dispatching','response_received','transport_failed','evaluated',"
            "'replay_scheduled','indeterminate') AND request_fingerprint IS NOT NULL "
            "AND primary_trace_id IS NOT NULL AND client_span_id IS NOT NULL "
            "AND dispatch_recorded_at IS NOT NULL) OR state = 'prepared' OR "
            "(state = 'failed' AND dispatch_certainty = 'not_started') OR "
            "(state = 'failed' AND dispatch_certainty <> 'not_started' "
            "AND request_fingerprint IS NOT NULL AND primary_trace_id IS NOT NULL "
            "AND client_span_id IS NOT NULL AND dispatch_recorded_at IS NOT NULL)",
            name="test_attempt_dispatch_shape",
        ),
        sa.CheckConstraint(
            "(state = 'prepared' AND request_fingerprint IS NULL AND primary_trace_id IS NULL "
            "AND client_span_id IS NULL AND dispatch_recorded_at IS NULL) OR "
            "(state = 'failed' AND dispatch_certainty = 'not_started' "
            "AND request_fingerprint IS NULL AND primary_trace_id IS NULL "
            "AND client_span_id IS NULL AND dispatch_recorded_at IS NULL) OR "
            "(state NOT IN ('prepared','failed') OR dispatch_certainty <> 'not_started')",
            name="test_attempt_pre_dispatch_fields",
        ),
        sa.CheckConstraint(
            "state <> 'response_received' OR (response_recorded_at IS NOT NULL "
            "AND dispatch_certainty = 'response_received' "
            "AND transport_outcome = 'response_received')",
            name="test_attempt_response_shape",
        ),
        sa.CheckConstraint(
            "state <> 'transport_failed' OR (transport_outcome IS NOT NULL "
            "AND transport_outcome <> 'response_received')",
            name="test_attempt_transport_failure_shape",
        ),
        sa.CheckConstraint(
            "(dispatch_certainty = 'not_sent' AND state = 'transport_failed' AND "
            "transport_outcome IN ('dns_failure','connect_timeout','connection_failure',"
            "'tls_failure','target_denied')) OR dispatch_certainty <> 'not_sent'",
            name="test_attempt_not_sent_shape",
        ),
        sa.CheckConstraint(
            "(state = 'dispatching' AND dispatch_certainty = 'possibly_sent') OR "
            "(state = 'response_received' AND dispatch_certainty = 'response_received' "
            "AND transport_outcome = 'response_received') OR "
            "(state = 'transport_failed' AND ((dispatch_certainty = 'not_sent' AND "
            "transport_outcome IN ('dns_failure','connect_timeout','connection_failure',"
            "'tls_failure','target_denied')) OR (dispatch_certainty = 'possibly_sent' AND "
            "transport_outcome IN ('write_timeout','write_failure','read_timeout','read_failure',"
            "'total_timeout','indeterminate','response_limit_exceeded')) OR "
            "(dispatch_certainty = 'response_received' AND transport_outcome IN "
            "('redirect_denied','read_timeout','read_failure','dns_failure','connect_timeout',"
            "'connection_failure','tls_failure','target_denied')))) OR "
            "(state IN ('evaluated','replay_scheduled','indeterminate') AND "
            "dispatch_certainty <> 'not_started') OR "
            "(state = 'prepared' AND dispatch_certainty = 'not_started') OR "
            "(state = 'failed')",
            name="test_attempt_outcome_matrix",
        ),
        sa.CheckConstraint(
            "redirect_rejection_code IS NULL OR transport_outcome = 'redirect_denied'",
            name="test_attempt_redirect_code_shape",
        ),
        sa.CheckConstraint(
            "replay_successor_id IS NULL OR replay_successor_id <> id",
            name="test_attempt_replay_not_self",
        ),
        sa.CheckConstraint(
            "state <> 'replay_scheduled' OR replay_successor_id IS NOT NULL",
            name="test_attempt_replay_shape",
        ),
        sa.ForeignKeyConstraint(
            ["execution_item_id"],
            ["execution_items.id"],
            ondelete="RESTRICT",
            name="fk_test_attempts_execution_item",
        ),
        sa.ForeignKeyConstraint(
            ["replay_successor_id"],
            ["test_attempts.id"],
            ondelete="RESTRICT",
            name="fk_test_attempts_replay_successor",
        ),
        sa.UniqueConstraint("execution_item_id", "sequence", name="uq_test_attempts_item_sequence"),
        sa.UniqueConstraint("replay_successor_id", name="uq_test_attempts_replay_successor"),
    )
    op.create_index(
        "ix_test_attempts_item_state", "test_attempts", ["execution_item_id", "state", "sequence"]
    )
    op.create_index(
        "ix_test_attempts_dispatching",
        "test_attempts",
        ["state", "dispatch_certainty", "dispatch_recorded_at"],
    )

    op.create_table(
        "response_artifacts",
        sa.Column("attempt_id", sa.Uuid(), primary_key=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("headers", JSONB(), nullable=False),
        sa.Column("body_kind", sa.String(16)),
        sa.Column("body_content", JSONB()),
        sa.Column("source_bytes_captured", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("redaction_unavailable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status_code BETWEEN 100 AND 599", name="response_artifact_status"),
        sa.CheckConstraint(
            "body_kind IS NULL OR body_kind IN ('json','text','bytes')",
            name="response_artifact_body_kind",
        ),
        sa.CheckConstraint("source_bytes_captured >= 0", name="response_artifact_source_bytes"),
        sa.CheckConstraint(
            "(body_kind IS NULL AND body_content IS NULL) OR "
            "(body_kind IS NOT NULL AND body_content IS NOT NULL)",
            name="response_artifact_body_shape",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempts.id"],
            ondelete="RESTRICT",
            name="fk_response_artifacts_attempt",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION sentinel_validate_attempt_links() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        DECLARE successor test_attempts%ROWTYPE;
        BEGIN
            IF NEW.state = 'response_received'
               AND NOT EXISTS (SELECT 1 FROM response_artifacts WHERE attempt_id = NEW.id) THEN
                RAISE EXCEPTION 'response_received attempt requires an artifact';
            END IF;
            IF NEW.state = 'transport_failed' AND NEW.dispatch_certainty = 'response_received' THEN
                IF NEW.transport_outcome IN ('redirect_denied','read_timeout','read_failure')
                   AND NOT EXISTS (SELECT 1 FROM response_artifacts WHERE attempt_id = NEW.id) THEN
                    RAISE EXCEPTION 'received transport failure requires an artifact';
                END IF;
            END IF;
            IF NEW.replay_successor_id IS NOT NULL THEN
                SELECT * INTO successor FROM test_attempts WHERE id = NEW.replay_successor_id;
                IF NOT FOUND OR successor.execution_item_id <> NEW.execution_item_id
                   OR successor.sequence <= NEW.sequence THEN
                    RAISE EXCEPTION 'invalid replay successor link';
                END IF;
                IF TG_OP = 'INSERT' THEN
                    IF successor.state <> 'prepared' THEN
                        RAISE EXCEPTION 'replay successor must be prepared when linked';
                    END IF;
                ELSIF OLD.replay_successor_id IS DISTINCT FROM NEW.replay_successor_id
                      AND successor.state <> 'prepared' THEN
                    RAISE EXCEPTION 'replay successor must be prepared when linked';
                END IF;
            END IF;
            IF EXISTS (SELECT 1 FROM test_attempts WHERE replay_successor_id = NEW.id) THEN
                IF EXISTS (
                    SELECT 1 FROM test_attempts predecessor
                    WHERE predecessor.replay_successor_id = NEW.id
                      AND (predecessor.execution_item_id <> NEW.execution_item_id
                           OR NEW.sequence <= predecessor.sequence)
                ) THEN
                    RAISE EXCEPTION 'replay successor ordering changed';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $fn$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER test_attempt_links_valid
        AFTER INSERT OR UPDATE ON test_attempts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION sentinel_validate_attempt_links();
        """
    )
    op.execute(
        """
        CREATE FUNCTION sentinel_validate_artifact_attachment() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        DECLARE attempt test_attempts%ROWTYPE;
        BEGIN
            SELECT * INTO attempt FROM test_attempts WHERE id = NEW.attempt_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'response artifact attempt is missing';
            END IF;
            IF NOT (
                attempt.state = 'response_received'
                OR (attempt.state = 'transport_failed'
                    AND attempt.dispatch_certainty = 'response_received'
                    AND attempt.transport_outcome IN
                        ('redirect_denied','read_timeout','read_failure'))
            ) THEN
                RAISE EXCEPTION 'response artifact is not allowed for attempt state';
            END IF;
            RETURN NEW;
        END;
        $fn$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER response_artifact_attachment_valid
        AFTER INSERT OR UPDATE ON response_artifacts
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION sentinel_validate_artifact_attachment();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS test_attempt_links_valid ON test_attempts")
    op.execute("DROP TRIGGER IF EXISTS response_artifact_attachment_valid ON response_artifacts")
    op.execute("DROP FUNCTION IF EXISTS sentinel_validate_attempt_links()")
    op.execute("DROP FUNCTION IF EXISTS sentinel_validate_artifact_attachment()")
    op.drop_table("response_artifacts")
    op.drop_index("ix_test_attempts_dispatching", table_name="test_attempts")
    op.drop_index("ix_test_attempts_item_state", table_name="test_attempts")
    op.drop_table("test_attempts")
