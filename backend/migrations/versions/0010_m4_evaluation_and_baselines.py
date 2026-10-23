"""Persist M4 evaluation results, immutable baselines, and activation history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_VERDICTS = (
    "'passed','functional_regression','performance_warning','observed_change',"
    "'inconclusive','baseline_required','not_evaluated'"
)
_MESSAGES = (
    "'assertion_passed','selected_value_match','duration_within_threshold',"
    "'status_mismatch','header_missing','header_mismatch','json_missing',"
    "'json_unexpected','json_type_mismatch','json_value_mismatch','text_mismatch',"
    "'invalid_json','selected_value_mismatch','normalizer_input_invalid',"
    "'baseline_missing','baseline_incompatible','content_missing','content_expired',"
    "'content_truncated','content_redacted','duration_exceeded','not_evaluated'"
)


def _add_contract_versions() -> None:
    op.add_column(
        "executions",
        sa.Column("result_contract_version", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "execution_result_contract_version",
        "executions",
        "result_contract_version BETWEEN 0 AND 1",
    )
    op.create_unique_constraint(
        "uq_executions_identity_contract_version",
        "executions",
        ["id", "result_contract_version"],
    )
    op.alter_column("executions", "result_contract_version", server_default="1")

    op.add_column(
        "execution_items",
        sa.Column("result_contract_version", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column("execution_items", sa.Column("baseline_activation_id", sa.Uuid()))
    op.add_column("execution_items", sa.Column("baseline_id", sa.Uuid()))
    op.execute(
        "UPDATE execution_items AS item "
        "SET result_contract_version = execution.result_contract_version "
        "FROM executions AS execution WHERE execution.id = item.execution_id"
    )
    op.create_check_constraint(
        "execution_item_result_contract_version",
        "execution_items",
        "result_contract_version BETWEEN 0 AND 1",
    )
    op.create_check_constraint(
        "execution_item_baseline_pin_shape",
        "execution_items",
        "(result_contract_version = 0 AND baseline_activation_id IS NULL AND baseline_id IS NULL) "
        "OR (result_contract_version = 1 AND ((baseline_activation_id IS NULL "
        "AND baseline_id IS NULL) "
        "OR (baseline_activation_id IS NOT NULL AND baseline_id IS NOT NULL)))",
    )
    op.create_unique_constraint(
        "uq_execution_items_identity_contract_version",
        "execution_items",
        ["id", "result_contract_version"],
    )
    op.create_foreign_key(
        "fk_execution_items_execution_contract_version",
        "execution_items",
        "executions",
        ["execution_id", "result_contract_version"],
        ["id", "result_contract_version"],
        ondelete="RESTRICT",
    )
    op.alter_column("execution_items", "result_contract_version", server_default="1")


def _create_baseline_tables() -> None:
    op.create_table(
        "baselines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("source_execution_id", sa.Uuid(), nullable=False),
        sa.Column("source_test_case_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_attempt_verdict", sa.String(32), nullable=False),
        sa.Column("source_finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("selected_values_schema_version", sa.SmallInteger(), nullable=False),
        sa.Column("selected_values", JSONB, nullable=False),
        sa.Column("reason", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="baseline_version"),
        sa.CheckConstraint(
            "source_attempt_verdict IN (" + _VERDICTS + ")", name="baseline_source_verdict"
        ),
        sa.CheckConstraint("length(policy_fingerprint) = 64", name="baseline_policy_fingerprint"),
        sa.CheckConstraint(
            "selected_values_schema_version = 1", name="baseline_selected_values_schema_version"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(selected_values) = 'object' AND selected_values ? 'schema_version' "
            "AND (selected_values ->> 'schema_version')::integer = 1 "
            "AND jsonb_typeof(selected_values -> 'values') = 'array' "
            "AND jsonb_array_length(selected_values -> 'values') <= 128",
            name="baseline_selected_values_shape",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR (octet_length(reason) BETWEEN 1 AND 500 "
            "AND reason !~ '[\\x00-\\x1F\\x7F]')",
            name="baseline_reason",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT", name="fk_baselines_project"
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id", "project_id"],
            ["test_cases.id", "test_cases.project_id"],
            ondelete="RESTRICT",
            name="fk_baselines_test_case_project",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id", "project_id"],
            ["environments.id", "environments.project_id"],
            ondelete="RESTRICT",
            name="fk_baselines_environment_project",
        ),
        sa.ForeignKeyConstraint(
            ["source_test_case_revision_id", "test_case_id"],
            ["test_case_revisions.id", "test_case_revisions.test_case_id"],
            ondelete="RESTRICT",
            name="fk_baselines_source_revision",
        ),
        sa.UniqueConstraint(
            "test_case_id", "environment_id", "version", name="uq_baselines_scope_version"
        ),
        sa.UniqueConstraint(
            "id", "test_case_id", "environment_id", "project_id", name="uq_baselines_identity_scope"
        ),
    )
    op.create_index(
        "ix_baselines_history", "baselines", ["test_case_id", "environment_id", "version", "id"]
    )
    op.create_index(
        "uq_baselines_source_attempt",
        "baselines",
        ["source_attempt_id"],
        unique=True,
    )

    op.create_table(
        "baseline_activations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_id", sa.Uuid(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.String(500)),
        sa.CheckConstraint(
            "deactivated_at IS NULL OR deactivated_at >= activated_at",
            name="baseline_activation_time_order",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR (octet_length(reason) BETWEEN 1 AND 500 "
            "AND reason !~ '[\\x00-\\x1F\\x7F]')",
            name="baseline_activation_reason",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="RESTRICT",
            name="fk_baseline_activations_project",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id", "project_id"],
            ["test_cases.id", "test_cases.project_id"],
            ondelete="RESTRICT",
            name="fk_baseline_activations_test_case_project",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id", "project_id"],
            ["environments.id", "environments.project_id"],
            ondelete="RESTRICT",
            name="fk_baseline_activations_environment_project",
        ),
        sa.ForeignKeyConstraint(
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
        sa.UniqueConstraint("id", "baseline_id", name="uq_baseline_activations_identity_baseline"),
    )
    op.create_index(
        "ix_baseline_activations_history",
        "baseline_activations",
        ["test_case_id", "environment_id", "baseline_id", "activated_at", "id"],
    )
    op.create_index(
        "uq_baseline_activations_current",
        "baseline_activations",
        ["test_case_id", "environment_id"],
        unique=True,
        postgresql_where=sa.text("deactivated_at IS NULL"),
    )


def _create_result_tables() -> None:
    op.create_foreign_key(
        "fk_execution_items_baseline_pin",
        "execution_items",
        "baseline_activations",
        ["baseline_activation_id", "baseline_id"],
        ["id", "baseline_id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "baseline_comparisons",
        sa.Column("attempt_id", sa.Uuid(), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("baseline_activation_id", sa.Uuid()),
        sa.Column("baseline_id", sa.Uuid()),
        sa.Column("baseline_version", sa.Integer()),
        sa.Column("policy_fingerprint", sa.String(64)),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('not_requested','missing','incompatible','compatible')",
            name="baseline_comparison_state",
        ),
        sa.CheckConstraint(
            "(state IN ('not_requested','missing') AND baseline_activation_id IS NULL "
            "AND baseline_id IS NULL AND baseline_version IS NULL "
            "AND policy_fingerprint IS NULL AND checked_at IS NOT NULL) "
            "OR (state IN ('incompatible','compatible') AND baseline_activation_id IS NOT NULL "
            "AND baseline_id IS NOT NULL AND baseline_version >= 1 "
            "AND policy_fingerprint IS NOT NULL AND checked_at IS NOT NULL)",
            name="baseline_comparison_reference_shape",
        ),
        sa.CheckConstraint(
            "policy_fingerprint IS NULL OR length(policy_fingerprint) = 64",
            name="baseline_comparison_policy_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempts.id"],
            ondelete="CASCADE",
            name="fk_baseline_comparisons_attempt",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_activation_id", "baseline_id"],
            ["baseline_activations.id", "baseline_activations.baseline_id"],
            ondelete="RESTRICT",
            name="fk_baseline_comparisons_activation_baseline",
        ),
    )
    op.create_index(
        "ix_baseline_comparisons_baseline",
        "baseline_comparisons",
        ["baseline_id", "checked_at", "attempt_id"],
    )

    op.create_table(
        "evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("rule_id", sa.Uuid()),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("message_code", sa.String(32), nullable=False),
        sa.Column("expected", JSONB),
        sa.Column("actual", JSONB),
        sa.Column("evidence_omitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 256", name="evaluation_ordinal"),
        sa.CheckConstraint(
            "kind IN ('assertion','baseline_selector','performance')", name="evaluation_kind"
        ),
        sa.CheckConstraint(
            "(kind = 'performance' AND rule_id IS NULL) OR "
            "(kind <> 'performance' AND rule_id IS NOT NULL)",
            name="evaluation_rule_shape",
        ),
        sa.CheckConstraint("severity IN ('required','advisory')", name="evaluation_severity"),
        sa.CheckConstraint(
            "kind <> 'performance' OR severity = 'advisory'",
            name="evaluation_performance_severity",
        ),
        sa.CheckConstraint(
            "outcome IN ('passed','failed','unevaluable','not_evaluated')",
            name="evaluation_outcome",
        ),
        sa.CheckConstraint("message_code IN (" + _MESSAGES + ")", name="evaluation_message_code"),
        sa.CheckConstraint(
            "expected IS NULL OR octet_length(expected::text) <= 4096",
            name="evaluation_expected_bound",
        ),
        sa.CheckConstraint(
            "actual IS NULL OR octet_length(actual::text) <= 4096",
            name="evaluation_actual_bound",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["test_attempts.id"], ondelete="CASCADE", name="fk_evaluations_attempt"
        ),
        sa.UniqueConstraint("attempt_id", "ordinal", name="uq_evaluations_attempt_ordinal"),
    )
    op.create_index("ix_evaluations_attempt_order", "evaluations", ["attempt_id", "ordinal"])


def _add_attempt_contract() -> None:
    op.add_column(
        "test_attempts",
        sa.Column("result_contract_version", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column("test_attempts", sa.Column("verdict", sa.String(32)))
    op.add_column("test_attempts", sa.Column("evaluation_error_code", sa.String(64)))
    op.drop_constraint("fk_test_attempts_execution_item", "test_attempts", type_="foreignkey")
    op.create_foreign_key(
        "fk_test_attempts_execution_item",
        "test_attempts",
        "execution_items",
        ["execution_item_id", "result_contract_version"],
        ["id", "result_contract_version"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "test_attempt_result_contract_version",
        "test_attempts",
        "result_contract_version BETWEEN 0 AND 1",
    )
    op.create_check_constraint(
        "test_attempt_verdict",
        "test_attempts",
        "verdict IS NULL OR verdict IN (" + _VERDICTS + ")",
    )
    op.create_check_constraint(
        "test_attempt_evaluation_error",
        "test_attempts",
        "evaluation_error_code IS NULL OR evaluation_error_code = 'platform_evaluation_failure'",
    )
    op.create_check_constraint(
        "test_attempt_evaluation_shape",
        "test_attempts",
        "(result_contract_version = 0 AND verdict IS NULL AND evaluation_error_code IS NULL) "
        "OR (result_contract_version = 1 AND ((state = 'evaluated' AND verdict IS NOT NULL "
        "AND evaluation_error_code IS NULL AND response_recorded_at IS NOT NULL "
        "AND dispatch_certainty = 'response_received' "
        "AND transport_outcome IN ('response_received','response_limit_exceeded')) "
        "OR (state = 'failed' AND verdict IS NULL AND evaluation_error_code IS NULL) "
        "OR (state = 'failed' AND verdict = 'inconclusive' "
        "AND evaluation_error_code = 'platform_evaluation_failure' "
        "AND dispatch_certainty = 'response_received' "
        "AND transport_outcome IN ('response_received','response_limit_exceeded')) "
        "OR (state NOT IN ('evaluated','failed') AND verdict IS NULL "
        "AND evaluation_error_code IS NULL)))",
    )
    op.alter_column("test_attempts", "result_contract_version", server_default="1")


def _install_m4_triggers() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sentinel_validate_m4_baseline_document() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        DECLARE entry jsonb; rule_ids integer;
        BEGIN
            IF jsonb_typeof(NEW.selected_values) <> 'object'
               OR NEW.selected_values ->> 'schema_version' <> '1'
               OR jsonb_typeof(NEW.selected_values -> 'values') <> 'array'
               OR jsonb_array_length(NEW.selected_values -> 'values') > 128
               OR octet_length(NEW.selected_values::text) > 1048576 THEN
                RAISE EXCEPTION 'invalid baseline selected values document';
            END IF;
            SELECT count(*) INTO rule_ids
            FROM (SELECT DISTINCT value ->> 'rule_id' AS rule_id
                  FROM jsonb_array_elements(NEW.selected_values -> 'values') AS value) AS ids;
            IF rule_ids <> jsonb_array_length(NEW.selected_values -> 'values') THEN
                RAISE EXCEPTION 'baseline selected values contain duplicate rule ids';
            END IF;
            FOR entry IN
                SELECT value FROM jsonb_array_elements(NEW.selected_values -> 'values') AS value
            LOOP
                IF jsonb_typeof(entry) <> 'object'
                   OR NOT (entry ?& ARRAY['rule_id','value'])
                   OR (SELECT count(*) FROM jsonb_object_keys(entry)) <> 2
                   OR entry ->> 'rule_id' !~
                      '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                   OR octet_length((entry -> 'value')::text) > 4096 THEN
                    RAISE EXCEPTION 'invalid baseline selected value';
                END IF;
            END LOOP;
            RETURN NEW;
        END;
        $fn$;

        CREATE OR REPLACE FUNCTION sentinel_protect_m4_baseline() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        BEGIN
            IF TG_OP = 'DELETE'
               AND current_setting('sentinel.project_deletion', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'baseline history is immutable';
        END;
        $fn$;

        CREATE OR REPLACE FUNCTION sentinel_protect_m4_activation() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF current_setting('sentinel.project_deletion', true) = 'on' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'baseline activation history is immutable';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.test_case_id IS DISTINCT FROM OLD.test_case_id
               OR NEW.environment_id IS DISTINCT FROM OLD.environment_id
               OR NEW.project_id IS DISTINCT FROM OLD.project_id
               OR NEW.baseline_id IS DISTINCT FROM OLD.baseline_id
               OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
               OR NEW.reason IS DISTINCT FROM OLD.reason
               OR OLD.deactivated_at IS NOT NULL
               OR NEW.deactivated_at IS NULL
               OR NEW.deactivated_at < OLD.activated_at THEN
                RAISE EXCEPTION 'baseline activation history is immutable';
            END IF;
            RETURN NEW;
        END;
        $fn$;

        CREATE OR REPLACE FUNCTION sentinel_validate_m4_pin_scope() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        BEGIN
            IF NEW.baseline_activation_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM baseline_activations activation
                    JOIN executions execution ON execution.id = NEW.execution_id
                    WHERE activation.id = NEW.baseline_activation_id
                      AND activation.baseline_id = NEW.baseline_id
                      AND activation.test_case_id = NEW.test_case_id
                      AND activation.environment_id = execution.environment_id
                      AND activation.project_id = NEW.project_id
                ) THEN
                    RAISE EXCEPTION 'execution item baseline pin is outside its scope';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $fn$;

        CREATE OR REPLACE FUNCTION sentinel_validate_m4_result_links() RETURNS trigger
        LANGUAGE plpgsql AS $fn$
        DECLARE target_attempt uuid; attempt_row test_attempts%ROWTYPE; comparison_count integer;
        BEGIN
            IF TG_TABLE_NAME = 'test_attempts' THEN
                IF TG_OP = 'DELETE' THEN
                    target_attempt := OLD.id;
                ELSE
                    target_attempt := NEW.id;
                END IF;
            ELSIF TG_OP = 'DELETE' THEN
                target_attempt := OLD.attempt_id;
            ELSE
                target_attempt := NEW.attempt_id;
            END IF;
            SELECT * INTO attempt_row FROM test_attempts WHERE id = target_attempt;
            IF NOT FOUND THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;
            SELECT count(*) INTO comparison_count
            FROM baseline_comparisons WHERE attempt_id = target_attempt;
            IF attempt_row.result_contract_version = 1 AND attempt_row.state = 'evaluated'
               AND comparison_count <> 1 THEN
                RAISE EXCEPTION 'evaluated attempt requires exactly one baseline comparison';
            END IF;
            IF attempt_row.result_contract_version <> 1 OR attempt_row.state <> 'evaluated' THEN
                IF comparison_count <> 0 OR EXISTS (
                    SELECT 1 FROM evaluations WHERE attempt_id = target_attempt
                ) THEN
                    RAISE EXCEPTION 'evaluation children require an evaluated version-1 attempt';
                END IF;
            END IF;
            IF EXISTS (
                SELECT 1
                FROM baseline_comparisons comparison
                JOIN test_attempts attempt ON attempt.id = comparison.attempt_id
                JOIN execution_items item ON item.id = attempt.execution_item_id
                JOIN executions execution ON execution.id = item.execution_id
                JOIN baseline_activations activation
                  ON activation.id = comparison.baseline_activation_id
                 AND activation.baseline_id = comparison.baseline_id
                WHERE comparison.attempt_id = target_attempt
                  AND (activation.test_case_id <> item.test_case_id
                       OR activation.environment_id <> execution.environment_id
                       OR activation.project_id <> item.project_id)
            ) THEN
                RAISE EXCEPTION 'baseline comparison is outside attempt scope';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM baseline_comparisons comparison
                JOIN baselines baseline ON baseline.id = comparison.baseline_id
                WHERE comparison.attempt_id = target_attempt
                  AND comparison.baseline_version <> baseline.version
            ) THEN
                RAISE EXCEPTION 'baseline comparison version does not match baseline';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $fn$;

        CREATE TRIGGER m4_baseline_document_valid
        BEFORE INSERT OR UPDATE ON baselines
        FOR EACH ROW EXECUTE FUNCTION sentinel_validate_m4_baseline_document();
        CREATE TRIGGER m4_baseline_immutable
        BEFORE UPDATE OR DELETE ON baselines
        FOR EACH ROW EXECUTE FUNCTION sentinel_protect_m4_baseline();
        CREATE TRIGGER m4_activation_immutable
        BEFORE UPDATE OR DELETE ON baseline_activations
        FOR EACH ROW EXECUTE FUNCTION sentinel_protect_m4_activation();
        CREATE CONSTRAINT TRIGGER m4_pin_scope_valid
        AFTER INSERT OR UPDATE ON execution_items
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION sentinel_validate_m4_pin_scope();
        CREATE CONSTRAINT TRIGGER m4_result_links_valid_attempt
        AFTER INSERT OR UPDATE OR DELETE ON test_attempts
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION sentinel_validate_m4_result_links();
        CREATE CONSTRAINT TRIGGER m4_result_links_valid_comparison
        AFTER INSERT OR UPDATE OR DELETE ON baseline_comparisons
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION sentinel_validate_m4_result_links();
        CREATE CONSTRAINT TRIGGER m4_result_links_valid_evaluation
        AFTER INSERT OR UPDATE OR DELETE ON evaluations
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION sentinel_validate_m4_result_links();
        """
    )


def upgrade() -> None:
    _add_contract_versions()
    _create_baseline_tables()
    _create_result_tables()
    _add_attempt_contract()
    _install_m4_triggers()
    op.execute(
        "SET CONSTRAINTS m4_pin_scope_valid, m4_result_links_valid_attempt, "
        "m4_result_links_valid_comparison, m4_result_links_valid_evaluation IMMEDIATE"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS m4_result_links_valid_evaluation ON evaluations; "
        "DROP TRIGGER IF EXISTS m4_result_links_valid_comparison ON baseline_comparisons; "
        "DROP TRIGGER IF EXISTS m4_result_links_valid_attempt ON test_attempts; "
        "DROP TRIGGER IF EXISTS m4_pin_scope_valid ON execution_items; "
        "DROP TRIGGER IF EXISTS m4_activation_immutable ON baseline_activations; "
        "DROP TRIGGER IF EXISTS m4_baseline_immutable ON baselines; "
        "DROP TRIGGER IF EXISTS m4_baseline_document_valid ON baselines; "
        "DROP FUNCTION IF EXISTS sentinel_validate_m4_result_links(); "
        "DROP FUNCTION IF EXISTS sentinel_validate_m4_pin_scope(); "
        "DROP FUNCTION IF EXISTS sentinel_protect_m4_activation(); "
        "DROP FUNCTION IF EXISTS sentinel_protect_m4_baseline(); "
        "DROP FUNCTION IF EXISTS sentinel_validate_m4_baseline_document();"
    )
    op.drop_index("ix_evaluations_attempt_order", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_index("ix_baseline_comparisons_baseline", table_name="baseline_comparisons")
    op.drop_table("baseline_comparisons")
    op.drop_constraint("fk_execution_items_baseline_pin", "execution_items", type_="foreignkey")
    op.drop_index("uq_baseline_activations_current", table_name="baseline_activations")
    op.drop_index("ix_baseline_activations_history", table_name="baseline_activations")
    op.drop_table("baseline_activations")
    op.drop_index("uq_baselines_source_attempt", table_name="baselines")
    op.drop_index("ix_baselines_history", table_name="baselines")
    op.drop_table("baselines")

    op.drop_constraint("test_attempt_evaluation_shape", "test_attempts", type_="check")
    op.drop_constraint("test_attempt_evaluation_error", "test_attempts", type_="check")
    op.drop_constraint("test_attempt_verdict", "test_attempts", type_="check")
    op.drop_constraint("test_attempt_result_contract_version", "test_attempts", type_="check")
    op.drop_constraint("fk_test_attempts_execution_item", "test_attempts", type_="foreignkey")
    op.create_foreign_key(
        "fk_test_attempts_execution_item",
        "test_attempts",
        "execution_items",
        ["execution_item_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("test_attempts", "evaluation_error_code")
    op.drop_column("test_attempts", "verdict")
    op.drop_column("test_attempts", "result_contract_version")

    op.drop_constraint(
        "fk_execution_items_execution_contract_version", "execution_items", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_execution_items_identity_contract_version", "execution_items", type_="unique"
    )
    op.drop_constraint("execution_item_baseline_pin_shape", "execution_items", type_="check")
    op.drop_constraint("execution_item_result_contract_version", "execution_items", type_="check")
    op.drop_column("execution_items", "baseline_id")
    op.drop_column("execution_items", "baseline_activation_id")
    op.drop_column("execution_items", "result_contract_version")
    op.drop_constraint("uq_executions_identity_contract_version", "executions", type_="unique")
    op.drop_constraint("execution_result_contract_version", "executions", type_="check")
    op.drop_column("executions", "result_contract_version")
