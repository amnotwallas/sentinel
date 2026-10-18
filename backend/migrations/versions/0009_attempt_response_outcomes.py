"""Preserve bounded accepted-response transport outcomes."""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RESPONSE_SHAPE_V0008 = (
    "state <> 'response_received' OR (response_recorded_at IS NOT NULL "
    "AND dispatch_certainty = 'response_received' "
    "AND transport_outcome = 'response_received')"
)
_RESPONSE_SHAPE_V0009 = (
    "state <> 'response_received' OR (response_recorded_at IS NOT NULL "
    "AND dispatch_certainty = 'response_received' "
    "AND transport_outcome IN ('response_received','response_limit_exceeded'))"
)
_OUTCOME_MATRIX_V0008 = (
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
    "(state = 'failed')"
)
_OUTCOME_MATRIX_V0009 = (
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
    "(state = 'failed')"
)


def _replace_constraints(
    *, response_shape: str, outcome_matrix: str, outcome_not_valid: bool = False
) -> None:
    op.drop_constraint("test_attempt_response_shape", "test_attempts", type_="check")
    op.drop_constraint("test_attempt_outcome_matrix", "test_attempts", type_="check")
    op.create_check_constraint("test_attempt_response_shape", "test_attempts", response_shape)
    op.create_check_constraint(
        "test_attempt_outcome_matrix",
        "test_attempts",
        outcome_matrix,
        postgresql_not_valid=outcome_not_valid,
    )


def _install_v0009_trigger_functions() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sentinel_validate_attempt_links() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        DECLARE
            successor test_attempts%ROWTYPE;
            artifact response_artifacts%ROWTYPE;
        BEGIN
            IF NEW.state = 'response_received' THEN
                SELECT * INTO artifact FROM response_artifacts WHERE attempt_id = NEW.id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'response_received attempt requires an artifact';
                END IF;
                IF (NEW.transport_outcome = 'response_limit_exceeded')
                   IS DISTINCT FROM artifact.truncated THEN
                    RAISE EXCEPTION 'response outcome and artifact truncation disagree';
                END IF;
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
        CREATE OR REPLACE FUNCTION sentinel_validate_artifact_attachment() RETURNS trigger
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
            IF attempt.state = 'response_received'
               AND (attempt.transport_outcome = 'response_limit_exceeded')
                   IS DISTINCT FROM NEW.truncated THEN
                RAISE EXCEPTION 'response outcome and artifact truncation disagree';
            END IF;
            RETURN NEW;
        END;
        $fn$;
        """
    )


def _install_v0008_trigger_functions() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sentinel_validate_attempt_links() RETURNS trigger
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
        CREATE OR REPLACE FUNCTION sentinel_validate_artifact_attachment() RETURNS trigger
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


def upgrade() -> None:
    _replace_constraints(
        response_shape=_RESPONSE_SHAPE_V0009,
        outcome_matrix=_OUTCOME_MATRIX_V0009,
        outcome_not_valid=True,
    )
    op.execute(
        "UPDATE test_attempts AS attempt "
        "SET transport_outcome = 'response_limit_exceeded' "
        "FROM response_artifacts AS artifact "
        "WHERE artifact.attempt_id = attempt.id "
        "AND attempt.state = 'response_received' "
        "AND attempt.transport_outcome = 'response_received' "
        "AND artifact.truncated"
    )
    _install_v0009_trigger_functions()
    op.execute("SET CONSTRAINTS test_attempt_links_valid IMMEDIATE")


def downgrade() -> None:
    # Restore 0008 validation before normalizing the precise outcome. Its
    # artifact retains the bounded/truncated evidence across the downgrade.
    _install_v0008_trigger_functions()
    op.execute(
        "UPDATE test_attempts SET transport_outcome = 'response_received' "
        "WHERE state = 'response_received' "
        "AND transport_outcome = 'response_limit_exceeded'"
    )
    op.execute("SET CONSTRAINTS test_attempt_links_valid IMMEDIATE")
    _replace_constraints(
        response_shape=_RESPONSE_SHAPE_V0008,
        outcome_matrix=_OUTCOME_MATRIX_V0008,
    )
