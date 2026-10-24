export interface paths {
    "/api/v1/attempts/{attempt_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Attempt */
        get: operations["get_attempt"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/environments/{environment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Environment */
        get: operations["get_environment"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update Environment */
        patch: operations["update_environment"];
        trace?: never;
    };
    "/api/v1/executions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Executions */
        get: operations["list_executions"];
        put?: never;
        /** Create Execution */
        post: operations["create_execution"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/executions/{execution_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Execution */
        get: operations["get_execution"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Projects */
        get: operations["list_projects"];
        put?: never;
        /** Create Project */
        post: operations["create_project"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects/{project_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Project */
        get: operations["get_project"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects/{project_id}/environments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Environments */
        get: operations["list_environments"];
        put?: never;
        /** Create Environment */
        post: operations["create_environment"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects/{project_id}/suites": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Suites */
        get: operations["list_suites"];
        put?: never;
        /** Create Suite */
        post: operations["create_suite"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/projects/{project_id}/test-cases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Test Cases */
        get: operations["list_test_cases"];
        put?: never;
        /** Create Test Case */
        post: operations["create_test_case"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/suites/{suite_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Suite */
        get: operations["get_suite"];
        /** Revise Suite */
        put: operations["revise_suite"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/test-cases/{test_case_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Test Case */
        get: operations["get_test_case"];
        /** Revise Test Case */
        put: operations["revise_test_case"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/test-cases/{test_case_id}/baseline-activations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Activate Baseline */
        post: operations["activate_baseline"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/test-cases/{test_case_id}/baselines": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Baselines */
        get: operations["list_baselines"];
        put?: never;
        /** Promote Baseline */
        post: operations["promote_baseline"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/test-cases/{test_case_id}/revisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Test Case Revisions */
        get: operations["list_test_case_revisions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Live */
        get: operations["live_health_live_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ready */
        get: operations["ready_health_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        Assertion: components["schemas"]["StatusCodeAssertion"] | components["schemas"]["HeaderPresentAssertion"] | components["schemas"]["HeaderEqualsAssertion"] | components["schemas"]["JSONPresentAssertion"] | components["schemas"]["JSONAbsentAssertion"] | components["schemas"]["JSONTypeAssertion"] | components["schemas"]["JSONEqualsAssertion"] | components["schemas"]["TextEqualsAssertion"];
        /** AttemptDetail */
        AttemptDetail: {
            baseline_comparison: components["schemas"]["BaselineComparisonOutput"];
            baseline_promotion: components["schemas"]["BaselinePromotionOutput"];
            /** Client Span Id */
            client_span_id: string | null;
            created_at: components["schemas"]["Timestamp"];
            dispatch_certainty: components["schemas"]["DispatchCertainty"];
            dispatch_recorded_at: components["schemas"]["Timestamp"] | null;
            /** Duration Ms */
            duration_ms: number | null;
            /** Evaluation Error Code */
            evaluation_error_code: "platform_evaluation_failure" | null;
            /** Evaluations */
            evaluations: components["schemas"]["EvaluationOutput"][];
            execution_id: components["schemas"]["UUID"];
            execution_item_id: components["schemas"]["UUID"];
            finished_at: components["schemas"]["Timestamp"] | null;
            id: components["schemas"]["UUID"];
            /** Included In Verdict */
            included_in_verdict: boolean;
            links: components["schemas"]["RelativeLinks"];
            observation: components["schemas"]["ResponseObservation"] | null;
            observation_state: components["schemas"]["ObservationState"];
            preparation_error_code: components["schemas"]["PreparationErrorCode"] | null;
            /** Primary Trace Id */
            primary_trace_id: string | null;
            redirect_rejection_code: components["schemas"]["RedirectRejectionCode"] | null;
            replayed_by_attempt_id: components["schemas"]["UUID"] | null;
            /** Request Fingerprint */
            request_fingerprint: string | null;
            response_recorded_at: components["schemas"]["Timestamp"] | null;
            /** Sequence */
            sequence: number;
            state: components["schemas"]["AttemptState"];
            transport_outcome: components["schemas"]["TransportOutcome"] | null;
            verdict: components["schemas"]["Verdict"] | null;
        };
        /**
         * AttemptState
         * @enum {string}
         */
        AttemptState: "prepared" | "dispatching" | "response_received" | "transport_failed" | "evaluated" | "replay_scheduled" | "indeterminate" | "failed";
        /** AttemptSummary */
        AttemptSummary: {
            /** Client Span Id */
            client_span_id: string | null;
            created_at: components["schemas"]["Timestamp"];
            dispatch_certainty: components["schemas"]["DispatchCertainty"];
            dispatch_recorded_at: components["schemas"]["Timestamp"] | null;
            /** Duration Ms */
            duration_ms: number | null;
            finished_at: components["schemas"]["Timestamp"] | null;
            id: components["schemas"]["UUID"];
            /** Included In Verdict */
            included_in_verdict: boolean;
            links: components["schemas"]["RelativeLinks"];
            preparation_error_code: components["schemas"]["PreparationErrorCode"] | null;
            /** Primary Trace Id */
            primary_trace_id: string | null;
            redirect_rejection_code: components["schemas"]["RedirectRejectionCode"] | null;
            replayed_by_attempt_id: components["schemas"]["UUID"] | null;
            response_recorded_at: components["schemas"]["Timestamp"] | null;
            /** Sequence */
            sequence: number;
            state: components["schemas"]["AttemptState"];
            transport_outcome: components["schemas"]["TransportOutcome"] | null;
            verdict: components["schemas"]["Verdict"] | null;
        };
        /** BaselineActivationBody */
        BaselineActivationBody: {
            /**
             * Baseline Id
             * Format: uuid
             */
            baseline_id: string;
            /**
             * Environment Id
             * Format: uuid
             */
            environment_id: string;
            /** Reason */
            reason: string | null;
        };
        /** BaselineActivationSummary */
        BaselineActivationSummary: {
            activated_at: components["schemas"]["Timestamp"];
            baseline_id: components["schemas"]["UUID"];
            /** Baseline Version */
            baseline_version: number;
            deactivated_at: components["schemas"]["Timestamp"] | null;
            environment_id: components["schemas"]["UUID"];
            id: components["schemas"]["UUID"];
            /** Reason */
            reason: string | null;
            test_case_id: components["schemas"]["UUID"];
        };
        /** BaselineComparisonOutput */
        BaselineComparisonOutput: {
            baseline_activation_id: components["schemas"]["UUID"] | null;
            baseline_id: components["schemas"]["UUID"] | null;
            /** Baseline Version */
            baseline_version: number | null;
            checked_at: components["schemas"]["Timestamp"] | null;
            /** Policy Fingerprint */
            policy_fingerprint: string | null;
            /**
             * State
             * @enum {string}
             */
            state: "not_requested" | "pending" | "not_evaluated" | "missing" | "incompatible" | "compatible";
        };
        /** BaselineCreateResult */
        BaselineCreateResult: {
            activation: components["schemas"]["BaselineActivationSummary"];
            baseline: components["schemas"]["BaselineSummary"];
        };
        /** BaselineLinks */
        BaselineLinks: {
            /** Source Attempt */
            source_attempt: string;
            /** Test Case */
            test_case: string;
        };
        /** BaselinePage */
        BaselinePage: {
            /** Items */
            items: components["schemas"]["BaselineSummary"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /** BaselinePromotionBody */
        BaselinePromotionBody: {
            /** Acknowledged Warnings */
            acknowledged_warnings: ("missing_baseline" | "incompatible_baseline" | "observed_change" | "performance_warning")[];
            /**
             * Confirmation
             * @constant
             */
            confirmation: "promote_selected_values";
            /**
             * Environment Id
             * Format: uuid
             */
            environment_id: string;
            /** Reason */
            reason: string | null;
            /**
             * Source Attempt Id
             * Format: uuid
             */
            source_attempt_id: string;
        };
        /** BaselinePromotionOutput */
        BaselinePromotionOutput: {
            /** Eligible */
            eligible: boolean;
            /** Ineligibility Codes */
            ineligibility_codes: ("no_selectors" | "attempt_not_evaluated" | "attempt_not_included" | "required_functional_check_failed" | "evaluation_inconclusive" | "selected_value_unavailable" | "selected_value_too_large" | "policy_mismatch" | "scope_mismatch")[];
            /** Warning Codes */
            warning_codes: ("missing_baseline" | "incompatible_baseline" | "observed_change" | "performance_warning")[];
        };
        /** BaselineSummary */
        BaselineSummary: {
            activated_at: components["schemas"]["Timestamp"] | null;
            /** Active */
            active: boolean;
            created_at: components["schemas"]["Timestamp"];
            environment_id: components["schemas"]["UUID"];
            id: components["schemas"]["UUID"];
            links: components["schemas"]["BaselineLinks"];
            /** Policy Fingerprint */
            policy_fingerprint: string;
            /** Reason */
            reason: string | null;
            source_attempt_id: components["schemas"]["UUID"];
            /**
             * Source Attempt Verdict
             * @enum {string}
             */
            source_attempt_verdict: "passed" | "functional_regression" | "performance_warning" | "observed_change" | "inconclusive" | "baseline_required" | "not_evaluated";
            source_execution_id: components["schemas"]["UUID"];
            source_finished_at: components["schemas"]["Timestamp"];
            source_test_case_revision_id: components["schemas"]["UUID"];
            test_case_id: components["schemas"]["UUID"];
            /** Version */
            version: number;
        };
        CIDR: string;
        CanonicalAssertion: components["schemas"]["StatusCodeAssertion"] | components["schemas"]["CanonicalHeaderPresentAssertion"] | components["schemas"]["CanonicalHeaderEqualsAssertion"] | components["schemas"]["JSONPresentAssertion"] | components["schemas"]["JSONAbsentAssertion"] | components["schemas"]["JSONTypeAssertion"] | components["schemas"]["JSONEqualsAssertion"] | components["schemas"]["TextEqualsAssertion"];
        CanonicalComparisonPolicy: {
            /** @default false */
            exact_text_body: boolean;
            /** @default null */
            performance_threshold_ms: number | null;
            /**
             * @default 1
             * @constant
             */
            schema_version: 1;
            selectors: components["schemas"]["CanonicalJSONSelector"][];
            /** @default null */
            text_body_selector: components["schemas"]["TextSelector"] | null;
        } & unknown;
        CanonicalEnvironmentDocument: {
            /** Format: uri */
            base_url: string;
            /**
             * @default 1
             * @constant
             */
            schema_version: 1;
            /** @default [] */
            secret_references: components["schemas"]["SecretReference"][];
            target_policy: components["schemas"]["CanonicalTargetPolicy"];
            /** @default {} */
            variables: {
                [key: string]: string;
            };
        };
        CanonicalHeaderEqualsAssertion: {
            expected: string;
            header_name: components["schemas"]["CanonicalHeaderName"];
            id: components["schemas"]["UUID"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "header_equals";
            severity: components["schemas"]["Severity"];
        };
        CanonicalHeaderName: string;
        CanonicalHeaderPresentAssertion: {
            header_name: components["schemas"]["CanonicalHeaderName"];
            id: components["schemas"]["UUID"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "header_present";
            severity: components["schemas"]["Severity"];
        };
        CanonicalJSONSelector: {
            id: components["schemas"]["UUID"];
            /**
             * @default {
             *       "name": "none",
             *       "version": 1
             *     }
             */
            normalizer: components["schemas"]["Normalizer"];
            pointer: components["schemas"]["JSONPointer"];
            severity: components["schemas"]["Severity"];
        };
        CanonicalRedaction: {
            header_names: components["schemas"]["CanonicalHeaderName"][];
            /** @default [] */
            json_pointers: components["schemas"]["JSONPointer"][];
            /**
             * @default 1
             * @constant
             */
            schema_version: 1;
        };
        CanonicalRequest: {
            /** @default null */
            body: components["schemas"]["RequestBody"] | null;
            /** @default 5000 */
            connect_timeout_ms: number;
            /** @default false */
            follow_redirects: boolean;
            headers: components["schemas"]["CanonicalRequestHeader"][];
            /** @default 3 */
            max_redirects: number;
            /** @default 262144 */
            max_response_bytes: number;
            method: components["schemas"]["Method"];
            path: string;
            /** @default [] */
            query: components["schemas"]["QueryParameter"][];
            /** @default 10000 */
            read_timeout_ms: number;
            /** @default 30000 */
            timeout_ms: number;
            /** @default true */
            verify_tls: boolean;
        };
        CanonicalRequestHeader: {
            name: components["schemas"]["CanonicalHeaderName"];
            value: string | components["schemas"]["SecretReference"];
        } & (unknown & unknown & unknown);
        CanonicalTargetPolicy: {
            /** @default [] */
            allowed_cidrs: components["schemas"]["CIDR"][];
            /** @default [] */
            allowed_hostnames: components["schemas"]["Hostname"][];
            /** @default null */
            allowed_ports: number[] | null;
            /** @default [] */
            denied_cidrs: components["schemas"]["CIDR"][];
            /** @default [] */
            denied_hostnames: components["schemas"]["Hostname"][];
            /**
             * @default 1
             * @constant
             */
            schema_version: 1;
        };
        CanonicalTestDefinition: {
            /** @default false */
            allow_unsafe_replay: boolean;
            assertions: components["schemas"]["CanonicalAssertion"][];
            comparison_policy: components["schemas"]["CanonicalComparisonPolicy"];
            redaction: components["schemas"]["CanonicalRedaction"];
            request: components["schemas"]["CanonicalRequest"];
            /**
             * @default 1
             * @constant
             */
            schema_version: 1;
        };
        /** ChangeEventOutput */
        ChangeEventOutput: {
            after_ref: components["schemas"]["UUID"] | null;
            before_ref: components["schemas"]["UUID"] | null;
            created_at: components["schemas"]["Timestamp"];
            id: components["schemas"]["UUID"];
            /**
             * Kind
             * @enum {string}
             */
            kind: "environment_created" | "environment_updated" | "test_case_created" | "test_case_revised" | "suite_created" | "suite_revised" | "baseline_activated";
            project_id: components["schemas"]["UUID"];
            subject_id: components["schemas"]["UUID"];
            /**
             * Subject Type
             * @enum {string}
             */
            subject_type: "environment" | "test_case" | "suite" | "baseline";
            summary: components["schemas"]["ChangeEventSummary"];
        };
        /** ChangeEventSummary */
        ChangeEventSummary: {
            /** Changed Fields */
            changed_fields: ("name" | "base_url" | "variables" | "secret_references" | "target_policy" | "request" | "assertions" | "comparison_policy" | "redaction" | "allow_unsafe_replay" | "suite_items" | "baseline_activation")[];
        };
        ComparisonPolicy: {
            /** @default false */
            exact_text_body?: boolean;
            /** @default null */
            performance_threshold_ms?: number | null;
            /**
             * @default 1
             * @constant
             */
            schema_version?: 1;
            /** @default [] */
            selectors?: components["schemas"]["JSONSelector"][];
            /** @default null */
            text_body_selector?: components["schemas"]["TextSelector"] | null;
        } & unknown;
        /** @description Opaque unpadded base64url of DecodedCursor. Decode<=1536 bytes; scope/filter validation remains application behavior. */
        Cursor: string;
        /** @description Finite original decimal token <=38 significant digits, adjusted exponent -128..128; canonical plain decimal/negative zero0; no binary float decision. */
        DecimalNumber: number;
        /**
         * DispatchCertainty
         * @enum {string}
         */
        DispatchCertainty: "not_started" | "not_sent" | "possibly_sent" | "response_received";
        EnvironmentCreate: {
            definition: components["schemas"]["EnvironmentDocument"];
            name: components["schemas"]["Name"];
        };
        EnvironmentDetail: {
            active_revision: components["schemas"]["EnvironmentRevision"];
            active_revision_id: components["schemas"]["UUID"];
            created_at: components["schemas"]["Timestamp"];
            id: components["schemas"]["UUID"];
            name: components["schemas"]["Name"];
            project_id: components["schemas"]["UUID"];
            updated_at: components["schemas"]["Timestamp"];
        };
        /** @description Exact tagged declarations, descriptive only; no aliases/grants/value or resolution. */
        EnvironmentDocument: {
            /** Format: uri */
            base_url: string;
            /**
             * @default 1
             * @constant
             */
            schema_version?: 1;
            /** @default [] */
            secret_references?: components["schemas"]["SecretReference"][];
            /**
             * @default {
             *       "allowed_cidrs": [],
             *       "allowed_hostnames": [],
             *       "allowed_ports": null,
             *       "denied_cidrs": [],
             *       "denied_hostnames": [],
             *       "schema_version": 1
             *     }
             */
            target_policy?: components["schemas"]["TargetPolicy"];
            /** @default {} */
            variables?: {
                [key: string]: string;
            };
        };
        /** @description Identity lists use complete summaries;revision history uses complete canonical revisions. Count/byte bounded keyset page. */
        EnvironmentPage: {
            items: components["schemas"]["EnvironmentSummary"][];
            next_cursor: components["schemas"]["Cursor"] | null;
        };
        /** @description Nonempty:whole definition replacement=>new revision;name-only=>state_version/change event,no revision. */
        EnvironmentPatch: {
            definition?: components["schemas"]["EnvironmentDocument"];
            name?: components["schemas"]["Name"];
        } | unknown | unknown;
        EnvironmentRevision: {
            created_at: components["schemas"]["Timestamp"];
            definition: components["schemas"]["CanonicalEnvironmentDocument"];
            environment_id: components["schemas"]["UUID"];
            id: components["schemas"]["UUID"];
            /** @constant */
            schema_version: 1;
            version: components["schemas"]["Version"];
        };
        EnvironmentSummary: {
            active_revision_id: components["schemas"]["UUID"];
            active_revision_version: components["schemas"]["Version"];
            created_at: components["schemas"]["Timestamp"];
            id: components["schemas"]["UUID"];
            name: components["schemas"]["Name"];
            project_id: components["schemas"]["UUID"];
            updated_at: components["schemas"]["Timestamp"];
        };
        /** EvaluationOutput */
        EvaluationOutput: {
            /** Actual */
            actual: unknown | null;
            /** Evidence Omitted */
            evidence_omitted: boolean;
            /** Expected */
            expected: unknown | null;
            id: components["schemas"]["UUID"];
            /**
             * Kind
             * @enum {string}
             */
            kind: "assertion" | "baseline_selector" | "performance";
            /**
             * Message Code
             * @enum {string}
             */
            message_code: "assertion_passed" | "selected_value_match" | "duration_within_threshold" | "status_mismatch" | "header_missing" | "header_mismatch" | "json_missing" | "json_unexpected" | "json_type_mismatch" | "json_value_mismatch" | "text_mismatch" | "invalid_json" | "selected_value_mismatch" | "normalizer_input_invalid" | "baseline_missing" | "baseline_incompatible" | "content_missing" | "content_expired" | "content_truncated" | "content_redacted" | "duration_exceeded" | "not_evaluated";
            /** Ordinal */
            ordinal: number;
            /**
             * Outcome
             * @enum {string}
             */
            outcome: "passed" | "failed" | "unevaluable" | "not_evaluated";
            /** Rule Id */
            rule_id: string | null;
            /**
             * Severity
             * @enum {string}
             */
            severity: "required" | "advisory";
        };
        /** ExecutionCreate */
        ExecutionCreate: components["schemas"]["ExecutionCreateTestCase"] | components["schemas"]["ExecutionCreateSuite"];
        ExecutionCreateSuite: {
            environment_id: components["schemas"]["UUID"];
            suite_id: components["schemas"]["UUID"];
        };
        ExecutionCreateTestCase: {
            environment_id: components["schemas"]["UUID"];
            test_case_id: components["schemas"]["UUID"];
        };
        /** ExecutionDetail */
        ExecutionDetail: {
            /** Change Evidence */
            change_evidence: components["schemas"]["ChangeEventOutput"][];
            /** Change Evidence Truncated */
            change_evidence_truncated: boolean;
            /** Completed Item Count */
            completed_item_count: number;
            created_at: components["schemas"]["Timestamp"];
            environment_id: components["schemas"]["UUID"];
            environment_revision_id: components["schemas"]["UUID"];
            finished_at: components["schemas"]["Timestamp"] | null;
            id: components["schemas"]["UUID"];
            /** Item Count */
            item_count: number;
            /** Items */
            items: components["schemas"]["ExecutionItem"][];
            links: components["schemas"]["RelativeLinks"];
            /** Pinned Change Events */
            pinned_change_events: components["schemas"]["ChangeEventOutput"][];
            project_id: components["schemas"]["UUID"];
            source_id: components["schemas"]["UUID"];
            source_revision_id: components["schemas"]["UUID"];
            /**
             * Source Type
             * @enum {string}
             */
            source_type: "test_case" | "suite";
            started_at: components["schemas"]["Timestamp"] | null;
            status: components["schemas"]["ExecutionStatus"];
            verdict: components["schemas"]["Verdict"] | null;
        };
        /** ExecutionItem */
        ExecutionItem: {
            /** Attempt Count */
            attempt_count: number;
            /** Attempts */
            attempts: components["schemas"]["AttemptSummary"][];
            /** Attempts Truncated */
            attempts_truncated: boolean;
            finished_at: components["schemas"]["Timestamp"] | null;
            id: components["schemas"]["UUID"];
            /** Ordinal */
            ordinal: number;
            started_at: components["schemas"]["Timestamp"] | null;
            status: components["schemas"]["ItemStatus"];
            test_case_id: components["schemas"]["UUID"];
            test_case_revision_id: components["schemas"]["UUID"];
            /** Test Case Revision Version */
            test_case_revision_version: number;
            verdict: components["schemas"]["Verdict"] | null;
        };
        /** ExecutionPage */
        ExecutionPage: {
            /** Items */
            items: components["schemas"]["ExecutionSummary"][];
            /** Next Cursor */
            next_cursor?: string | null;
        };
        /**
         * ExecutionStatus
         * @enum {string}
         */
        ExecutionStatus: "queued" | "running" | "completed" | "failed";
        /** ExecutionSummary */
        ExecutionSummary: {
            /** Completed Item Count */
            completed_item_count: number;
            created_at: components["schemas"]["Timestamp"];
            environment_id: components["schemas"]["UUID"];
            environment_revision_id: components["schemas"]["UUID"];
            finished_at: components["schemas"]["Timestamp"] | null;
            id: components["schemas"]["UUID"];
            /** Item Count */
            item_count: number;
            links: components["schemas"]["RelativeLinks"];
            project_id: components["schemas"]["UUID"];
            source_id: components["schemas"]["UUID"];
            source_revision_id: components["schemas"]["UUID"];
            /**
             * Source Type
             * @enum {string}
             */
            source_type: "test_case" | "suite";
            started_at: components["schemas"]["Timestamp"] | null;
            status: components["schemas"]["ExecutionStatus"];
            verdict: components["schemas"]["Verdict"] | null;
        };
        /** FieldError */
        FieldError: {
            /**
             * Code
             * @enum {string}
             */
            code: "required" | "type_invalid" | "value_invalid" | "extra_field" | "limit_exceeded" | "duplicate" | "invalid_uuid" | "invalid_url" | "invalid_json_pointer" | "invalid_secret_reference" | "secret_placement_forbidden" | "credential_literal_forbidden" | "trace_context_forbidden" | "unsafe_replay_acknowledgement_required" | "incompatible_fields" | "cursor_invalid";
            /**
             * Location
             * @enum {string}
             */
            location: "body" | "path" | "query" | "header";
            /** Message */
            message: string;
            /** Pointer */
            pointer: string;
        };
        HeaderEqualsAssertion: {
            expected: string;
            header_name: components["schemas"]["HeaderName"];
            id: components["schemas"]["UUID"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "header_equals";
            severity: components["schemas"]["Severity"];
        };
        HeaderName: string;
        HeaderPresentAssertion: {
            header_name: components["schemas"]["HeaderName"];
            id: components["schemas"]["UUID"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "header_present";
            severity: components["schemas"]["Severity"];
        };
        /** @description Exact lowercase IDNA; no wildcard/port/template/trailing dot; IP uses CIDR. */
        Hostname: string;
        /**
         * ItemStatus
         * @enum {string}
         */
        ItemStatus: "pending" | "running" | "completed" | "indeterminate" | "failed" | "skipped";
        JSONAbsentAssertion: {
            id: components["schemas"]["UUID"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "json_absent";
            pointer: components["schemas"]["JSONPointer"];
            severity: components["schemas"]["Severity"];
        };
        JSONBody: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "json";
            value: components["schemas"]["JSONValueWithSecretLeaves"];
        };
        JSONEqualsAssertion: {
            expected: components["schemas"]["JSONValue"];
            id: components["schemas"]["UUID"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "json_equals";
            pointer: components["schemas"]["JSONPointer"];
            severity: components["schemas"]["Severity"];
        };
        JSONPointer: string;
        JSONPresentAssertion: {
            id: components["schemas"]["UUID"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "json_present";
            pointer: components["schemas"]["JSONPointer"];
            severity: components["schemas"]["Severity"];
        };
        JSONSelector: {
            id: components["schemas"]["UUID"];
            /**
             * @default {
             *       "name": "none",
             *       "version": 1
             *     }
             */
            normalizer?: components["schemas"]["Normalizer"];
            pointer: components["schemas"]["JSONPointer"];
            severity: components["schemas"]["Severity"];
        };
        JSONTypeAssertion: {
            /** @enum {string} */
            expected_type: "null" | "boolean" | "number" | "string" | "array" | "object";
            id: components["schemas"]["UUID"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "json_type";
            pointer: components["schemas"]["JSONPointer"];
            severity: components["schemas"]["Severity"];
        };
        JSONValue: GeneratedJSONValue;
        JSONValueWithSecretLeaves: GeneratedJSONValueWithSecretLeaves;
        /** Liveness */
        Liveness: {
            /**
             * Status
             * @default alive
             * @constant
             */
            status?: "alive";
        };
        /** @enum {string} */
        Method: "GET" | "HEAD" | "OPTIONS" | "POST" | "PUT" | "PATCH" | "DELETE";
        /** @description Normalize before 1..120 code-point bounds; case-sensitive equality. */
        Name: string;
        NoneNormalizer: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            name: "none";
            /** @constant */
            version: 1;
        };
        /** @description Validate named versioned policy in M2 only. Invalid runtime input yields explicit error;M4 verdict mapping unresolved. */
        Normalizer: components["schemas"]["NoneNormalizer"] | components["schemas"]["SortScalarArrayNormalizer"] | components["schemas"]["RoundDecimalNormalizer"];
        /**
         * ObservationState
         * @enum {string}
         */
        ObservationState: "not_recorded" | "available" | "expired" | "omitted";
        /**
         * PreparationErrorCode
         * @enum {string}
         */
        PreparationErrorCode: "secret_missing" | "template_variable_missing" | "target_policy_denied" | "request_invalid" | "tls_verification_required" | "infrastructure_failure";
        /** Problem */
        Problem: {
            /**
             * Code
             * @enum {string}
             */
            code: "validation_failed" | "secret_reference_invalid" | "resource_not_found" | "revision_conflict" | "revision_precondition_required" | "resource_conflict" | "request_too_large" | "unsupported_media_type" | "authentication_required" | "forbidden_origin" | "idempotency_conflict" | "baseline_ineligible" | "baseline_incompatible" | "baseline_confirmation_required" | "internal_error" | "http_error";
            /** Errors */
            errors?: components["schemas"]["FieldError"][];
            /** Status */
            status: number;
            /** Title */
            title: string;
            /** Type */
            type: string;
        } & ({
            /** @constant */
            code?: "validation_failed";
            /** @constant */
            status?: 422;
            /** @constant */
            title?: "Request validation failed";
            /** @constant */
            type?: "urn:sentinel:problem:validation_failed";
        } | {
            /** @constant */
            code?: "secret_reference_invalid";
            /** @constant */
            status?: 422;
            /** @constant */
            title?: "Secret reference invalid";
            /** @constant */
            type?: "urn:sentinel:problem:secret_reference_invalid";
        } | {
            /** @constant */
            code?: "resource_not_found";
            /** @constant */
            status?: 404;
            /** @constant */
            title?: "Request failed";
            /** @constant */
            type?: "urn:sentinel:problem:resource_not_found";
        } | {
            /** @constant */
            code?: "revision_conflict";
            /** @constant */
            status?: 412;
            /** @constant */
            title?: "Revision conflict";
            /** @constant */
            type?: "urn:sentinel:problem:revision_conflict";
        } | {
            /** @constant */
            code?: "revision_precondition_required";
            /** @constant */
            status?: 428;
            /** @constant */
            title?: "Revision precondition required";
            /** @constant */
            type?: "urn:sentinel:problem:revision_precondition_required";
        } | {
            /** @constant */
            code?: "resource_conflict";
            /** @constant */
            status?: 409;
            /** @constant */
            title?: "Resource conflict";
            /** @constant */
            type?: "urn:sentinel:problem:resource_conflict";
        } | {
            /** @constant */
            code?: "request_too_large";
            /** @constant */
            status?: 413;
            /** @constant */
            title?: "Request too large";
            /** @constant */
            type?: "urn:sentinel:problem:request_too_large";
        } | {
            /** @constant */
            code?: "unsupported_media_type";
            /** @constant */
            status?: 415;
            /** @constant */
            title?: "Unsupported media type";
            /** @constant */
            type?: "urn:sentinel:problem:unsupported_media_type";
        } | {
            /** @constant */
            code?: "authentication_required";
            /** @constant */
            status?: 401;
            /** @constant */
            title?: "Authentication required";
            /** @constant */
            type?: "urn:sentinel:problem:authentication_required";
        } | {
            /** @constant */
            code?: "forbidden_origin";
            /** @constant */
            status?: 403;
            /** @constant */
            title?: "Forbidden origin";
            /** @constant */
            type?: "urn:sentinel:problem:forbidden_origin";
        } | {
            /** @constant */
            code?: "idempotency_conflict";
            /** @constant */
            status?: 409;
            /** @constant */
            title?: "Idempotency conflict";
            /** @constant */
            type?: "urn:sentinel:problem:idempotency_conflict";
        } | {
            /** @constant */
            code?: "baseline_ineligible";
            /** @constant */
            status?: 409;
            /** @constant */
            title?: "Baseline ineligible";
            /** @constant */
            type?: "urn:sentinel:problem:baseline_ineligible";
        } | {
            /** @constant */
            code?: "baseline_incompatible";
            /** @constant */
            status?: 409;
            /** @constant */
            title?: "Baseline incompatible";
            /** @constant */
            type?: "urn:sentinel:problem:baseline_incompatible";
        } | {
            /** @constant */
            code?: "baseline_confirmation_required";
            /** @constant */
            status?: 409;
            /** @constant */
            title?: "Baseline confirmation required";
            /** @constant */
            type?: "urn:sentinel:problem:baseline_confirmation_required";
        } | {
            /** @constant */
            code?: "internal_error";
            /** @constant */
            status?: 500;
            /** @constant */
            title?: "Internal server error";
            /** @constant */
            type?: "urn:sentinel:problem:internal_error";
        } | {
            /** @constant */
            code?: "http_error";
            /** @constant */
            status?: 405;
            /** @constant */
            title?: "Request failed";
            /** @constant */
            type?: "urn:sentinel:problem:http_error";
        });
        Project: {
            created_at: components["schemas"]["Timestamp"];
            /** @description M2 deletion excluded. */
            deleted_at: null;
            id: components["schemas"]["UUID"];
            name: components["schemas"]["Name"];
        };
        ProjectCreate: {
            name: components["schemas"]["Name"];
        };
        /** @description Identity lists use complete summaries;revision history uses complete canonical revisions. Count/byte bounded keyset page. */
        ProjectPage: {
            items: components["schemas"]["Project"][];
            next_cursor: components["schemas"]["Cursor"] | null;
        };
        QueryParameter: {
            name: string;
            value: string;
        };
        /** Readiness */
        Readiness: {
            /**
             * Postgres
             * @enum {string}
             */
            postgres: "available" | "unavailable";
            /**
             * Status
             * @enum {string}
             */
            status: "ready" | "unavailable";
            /**
             * Tempo
             * @enum {string}
             */
            tempo: "available" | "unavailable";
        };
        /** @description Additional response protections;cannot disable fixed credential redaction. */
        Redaction: {
            /** @default [] */
            header_names?: components["schemas"]["HeaderName"][];
            /** @default [] */
            json_pointers?: components["schemas"]["JSONPointer"][];
            /**
             * @default 1
             * @constant
             */
            schema_version?: 1;
        };
        /**
         * RedirectRejectionCode
         * @enum {string}
         */
        RedirectRejectionCode: "method_not_allowed" | "location_missing" | "location_invalid" | "scheme_denied" | "port_denied" | "target_denied" | "redirect_limit_exceeded";
        /** RelativeLinks */
        RelativeLinks: {
            /** Self */
            self: string;
        };
        Request: {
            /** @default null */
            body?: components["schemas"]["RequestBody"] | null;
            /** @default 5000 */
            connect_timeout_ms?: number;
            /** @default false */
            follow_redirects?: boolean;
            /** @default [] */
            headers?: components["schemas"]["RequestHeader"][];
            /** @default 3 */
            max_redirects?: number;
            /** @default 262144 */
            max_response_bytes?: number;
            method: components["schemas"]["Method"];
            path: string;
            /** @default [] */
            query?: components["schemas"]["QueryParameter"][];
            /** @default 10000 */
            read_timeout_ms?: number;
            /** @default 30000 */
            timeout_ms?: number;
            /** @default true */
            verify_tls?: boolean;
        };
        RequestBody: components["schemas"]["JSONBody"] | components["schemas"]["TextBody"];
        RequestHeader: {
            name: components["schemas"]["HeaderName"];
            value: string | components["schemas"]["SecretReference"];
        } & (unknown & unknown & unknown);
        /** ResponseHeader */
        ResponseHeader: {
            /** Name */
            name: string;
            /** Value */
            value: string;
        };
        /** ResponseObservation */
        ResponseObservation: {
            /** Body */
            body: string | null;
            /**
             * Body Kind
             * @enum {string}
             */
            body_kind: "json" | "text" | "omitted";
            /** Captured Bytes */
            captured_bytes: number;
            expires_at: components["schemas"]["Timestamp"];
            /** Headers */
            headers: components["schemas"]["ResponseHeader"][];
            id: components["schemas"]["UUID"];
            recorded_at: components["schemas"]["Timestamp"];
            /** Redaction Unavailable */
            redaction_unavailable: boolean;
            /** Status Code */
            status_code: number | null;
            /** Truncated */
            truncated: boolean;
        };
        RoundDecimalNormalizer: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            name: "round_decimal";
            /** @constant */
            rounding: "half_even";
            scale: number;
            /** @constant */
            version: 1;
        };
        SHA256: string;
        SecretName: string;
        SecretReference: {
            $secret: components["schemas"]["SecretName"];
        };
        /** @enum {string} */
        Severity: "required" | "advisory";
        SortScalarArrayNormalizer: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            name: "sort_scalar_array";
            /** @constant */
            version: 1;
        };
        StatusCodeAssertion: {
            expected_codes: number[];
            id: components["schemas"]["UUID"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "status_code";
            severity: components["schemas"]["Severity"];
        };
        SuiteDetail: {
            active_revision: components["schemas"]["SuiteRevision"];
            active_revision_id: components["schemas"]["UUID"];
            created_at: components["schemas"]["Timestamp"];
            id: components["schemas"]["UUID"];
            name: components["schemas"]["Name"];
            project_id: components["schemas"]["UUID"];
            updated_at: components["schemas"]["Timestamp"];
        };
        /** @description Identity lists use complete summaries;revision history uses complete canonical revisions. Count/byte bounded keyset page. */
        SuitePage: {
            items: components["schemas"]["SuiteSummary"][];
            next_cursor: components["schemas"]["Cursor"] | null;
        };
        SuiteRevision: {
            created_at: components["schemas"]["Timestamp"];
            id: components["schemas"]["UUID"];
            items: components["schemas"]["SuiteRevisionItem"][];
            /** @constant */
            schema_version: 1;
            suite_id: components["schemas"]["UUID"];
            version: components["schemas"]["Version"];
        };
        SuiteRevisionItem: {
            ordinal: number;
            test_case_id: components["schemas"]["UUID"];
            test_case_revision_id: components["schemas"]["UUID"];
            test_case_revision_version: components["schemas"]["Version"];
        };
        SuiteSummary: {
            active_revision_id: components["schemas"]["UUID"];
            active_revision_version: components["schemas"]["Version"];
            created_at: components["schemas"]["Timestamp"];
            id: components["schemas"]["UUID"];
            name: components["schemas"]["Name"];
            project_id: components["schemas"]["UUID"];
            updated_at: components["schemas"]["Timestamp"];
        };
        SuiteWrite: {
            name: components["schemas"]["Name"];
            test_case_revision_ids: components["schemas"]["UUID"][];
        };
        TargetPolicy: {
            /** @default [] */
            allowed_cidrs?: components["schemas"]["CIDR"][];
            /** @default [] */
            allowed_hostnames?: components["schemas"]["Hostname"][];
            /** @default null */
            allowed_ports?: number[] | null;
            /** @default [] */
            denied_cidrs?: components["schemas"]["CIDR"][];
            /** @default [] */
            denied_hostnames?: components["schemas"]["Hostname"][];
            /**
             * @default 1
             * @constant
             */
            schema_version?: 1;
        };
        TestCaseDetail: {
            active_revision: components["schemas"]["TestCaseRevision"];
            active_revision_id: components["schemas"]["UUID"];
            created_at: components["schemas"]["Timestamp"];
            id: components["schemas"]["UUID"];
            name: components["schemas"]["Name"];
            project_id: components["schemas"]["UUID"];
            updated_at: components["schemas"]["Timestamp"];
        };
        /** @description Identity lists use complete summaries;revision history uses complete canonical revisions. Count/byte bounded keyset page. */
        TestCasePage: {
            items: components["schemas"]["TestCaseSummary"][];
            next_cursor: components["schemas"]["Cursor"] | null;
        };
        TestCaseRevision: {
            created_at: components["schemas"]["Timestamp"];
            definition: components["schemas"]["CanonicalTestDefinition"];
            id: components["schemas"]["UUID"];
            policy_fingerprint: components["schemas"]["SHA256"];
            /** @constant */
            schema_version: 1;
            test_case_id: components["schemas"]["UUID"];
            unsafe_replay_acknowledged_at: components["schemas"]["Timestamp"] | null;
            version: components["schemas"]["Version"];
        };
        /** @description Identity lists use complete summaries;revision history uses complete canonical revisions. Count/byte bounded keyset page. */
        TestCaseRevisionPage: {
            items: components["schemas"]["TestCaseRevision"][];
            next_cursor: components["schemas"]["Cursor"] | null;
        };
        TestCaseSummary: {
            active_revision_id: components["schemas"]["UUID"];
            active_revision_version: components["schemas"]["Version"];
            created_at: components["schemas"]["Timestamp"];
            id: components["schemas"]["UUID"];
            name: components["schemas"]["Name"];
            project_id: components["schemas"]["UUID"];
            updated_at: components["schemas"]["Timestamp"];
        };
        TestCaseWrite: {
            definition: components["schemas"]["TestDefinition"];
            name: components["schemas"]["Name"];
            /** @default null */
            unsafe_replay_acknowledgement?: "duplicate_effects_possible" | null;
        } & unknown;
        TestDefinition: {
            /** @default false */
            allow_unsafe_replay?: boolean;
            /** @default [] */
            assertions?: components["schemas"]["Assertion"][];
            /**
             * @default {
             *       "exact_text_body": false,
             *       "performance_threshold_ms": null,
             *       "schema_version": 1,
             *       "selectors": [],
             *       "text_body_selector": null
             *     }
             */
            comparison_policy?: components["schemas"]["ComparisonPolicy"];
            /**
             * @default {
             *       "header_names": [],
             *       "json_pointers": [],
             *       "schema_version": 1
             *     }
             */
            redaction?: components["schemas"]["Redaction"];
            request: components["schemas"]["Request"];
            /**
             * @default 1
             * @constant
             */
            schema_version?: 1;
        };
        TextBody: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "text";
            value: string;
        };
        TextEqualsAssertion: {
            expected: string;
            id: components["schemas"]["UUID"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "text_equals";
            severity: components["schemas"]["Severity"];
        };
        TextSelector: {
            id: components["schemas"]["UUID"];
            severity: components["schemas"]["Severity"];
        };
        /** Format: date-time */
        Timestamp: string;
        /**
         * TransportOutcome
         * @enum {string}
         */
        TransportOutcome: "response_received" | "dns_failure" | "connect_timeout" | "connection_failure" | "tls_failure" | "write_timeout" | "write_failure" | "read_timeout" | "read_failure" | "total_timeout" | "target_denied" | "redirect_denied" | "response_limit_exceeded" | "indeterminate";
        /** Format: uuid */
        UUID: string;
        VariableName: string;
        /**
         * Verdict
         * @enum {string}
         */
        Verdict: "passed" | "functional_regression" | "performance_warning" | "observed_change" | "inconclusive" | "baseline_required" | "not_evaluated";
        Version: number;
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    get_attempt: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                attempt_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttemptDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_environment: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                environment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnvironmentDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    update_environment: {
        parameters: {
            query?: never;
            header: {
                "if-match": string | null;
            };
            path: {
                environment_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EnvironmentPatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnvironmentDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            412: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_executions: {
        parameters: {
            query?: {
                limit?: number;
                cursor?: string | null;
                project_id?: components["schemas"]["UUID"];
                environment_id?: components["schemas"]["UUID"];
                test_case_id?: components["schemas"]["UUID"];
                suite_id?: components["schemas"]["UUID"];
                status?: components["schemas"]["ExecutionStatus"] | null;
                verdict?: components["schemas"]["Verdict"] | null;
                created_from?: components["schemas"]["Timestamp"];
                created_before?: components["schemas"]["Timestamp"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionPage"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_execution: {
        parameters: {
            query?: never;
            header?: {
                "Idempotency-Key"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExecutionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    /** @description Created resource path */
                    Location?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_execution: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                execution_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_projects: {
        parameters: {
            query?: {
                limit?: number;
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectPage"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_project: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProjectCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    /** @description Created resource path */
                    Location?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Project"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_project: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Project"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_environments: {
        parameters: {
            query?: {
                limit?: number;
                cursor?: string | null;
            };
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnvironmentPage"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_environment: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EnvironmentCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    /** @description Created resource path */
                    Location?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnvironmentDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            412: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_suites: {
        parameters: {
            query?: {
                limit?: number;
                cursor?: string | null;
            };
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuitePage"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_suite: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SuiteWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    /** @description Created resource path */
                    Location?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuiteDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            412: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_test_cases: {
        parameters: {
            query?: {
                limit?: number;
                cursor?: string | null;
            };
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TestCasePage"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    create_test_case: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TestCaseWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    /** @description Created resource path */
                    Location?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TestCaseDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            412: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_suite: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                suite_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuiteDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            412: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    revise_suite: {
        parameters: {
            query?: never;
            header: {
                "if-match": string | null;
            };
            path: {
                suite_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SuiteWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuiteDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            412: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    get_test_case: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                test_case_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TestCaseDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            412: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    revise_test_case: {
        parameters: {
            query?: never;
            header: {
                "if-match": string | null;
            };
            path: {
                test_case_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TestCaseWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description Strong resource ETag */
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TestCaseDetail"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            412: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    activate_baseline: {
        parameters: {
            query?: never;
            header: {
                "If-Match": string;
            };
            path: {
                test_case_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BaselineActivationBody"];
            };
        };
        responses: {
            /** @description OK */
            200: {
                headers: {
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BaselineActivationSummary"];
                };
            };
            /** @description Successful Response */
            201: {
                headers: {
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BaselineActivationSummary"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_baselines: {
        parameters: {
            query: {
                environment_id: string;
                limit?: number;
                cursor?: string | null;
            };
            header?: never;
            path: {
                test_case_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BaselinePage"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    promote_baseline: {
        parameters: {
            query?: never;
            header: {
                "If-Match": string;
            };
            path: {
                test_case_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BaselinePromotionBody"];
            };
        };
        responses: {
            /** @description OK */
            200: {
                headers: {
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BaselineCreateResult"];
                };
            };
            /** @description Successful Response */
            201: {
                headers: {
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BaselineCreateResult"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            428: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    list_test_case_revisions: {
        parameters: {
            query?: {
                limit?: number;
                cursor?: string | null;
            };
            header?: never;
            path: {
                test_case_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TestCaseRevisionPage"];
                };
            };
            /** @description RFC 9457 problem response */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description RFC 9457 problem response */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    live_health_live_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Liveness"];
                };
            };
        };
    };
    ready_health_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Readiness"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Readiness"];
                };
            };
        };
    };
}
export type GeneratedJSONValue = null | boolean | components["schemas"]["DecimalNumber"] | string | GeneratedJSONValue[] | {
    [key: string]: GeneratedJSONValue;
};
export type GeneratedJSONValueWithSecretLeaves = null | boolean | components["schemas"]["DecimalNumber"] | string | GeneratedJSONValueWithSecretLeaves[] | {
    [key: string]: GeneratedJSONValueWithSecretLeaves;
} | components["schemas"]["SecretReference"];
