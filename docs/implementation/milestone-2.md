# Milestone 2 wire contracts and integration packet

Status: **PASS**. M2-00 through M2-08 are integrated on `main` at accepted implementation SHA `6b83adf0b8c9d9dcb0bba668a9e15d8ff0b4d715`. Prepared from [AGENTS.md](../../AGENTS.md), [MVP](../MVP.md), [roadmap](../ROADMAP.md), [architecture](../architecture/README.md), accepted ADRs 0001–0007, the actual catalog persistence, and the [task plan](../development/milestone-2-plan.md). The coordinator owns this contract. Changes to these wire choices require an explicit contract handoff; material architecture changes require an ADR. This acceptance does not authorize Milestone 3 implementation.

## Implementation ledger

M2-06 immutable test cases are integrated on `main` as
`3c50c2bb05f68a15c83df4312f7b1877797ce426`. The user confirmed GitHub Actions
workflow #5 reported success for that SHA. Local verification recorded 160
non-integration backend tests, 47 PostgreSQL integration tests, 8 frontend
tests, migration upgrade/downgrade/drift checks, generated-contract checks, and
Compose/worker/readiness smoke checks. The M2-06 acceptance review found and
corrected seven defects covering ETag handling, ownership constraints, bounded
history responses, sanitized secret/replay errors, version exhaustion, exact
decimal persistence, and runtime/generated OpenAPI alignment. M2-07 ordered
suites are integrated on `main` at
`1e396ddff50893fc4b6bd0db320075f90faf186f`; the user reported GitHub Actions
workflow #6 succeeded for that SHA.

M2-08 independently reviewed the combined catalog and corrected five
confirmed findings: environment active-revision ownership, environment version
exhaustion, environment ETag edge semantics, project/environment runtime OpenAPI
fidelity, and environment null/error-pointer boundary behavior. The accepted
candidate passed 176 non-integration backend tests, 59 real-PostgreSQL tests
(235 total), 9 frontend tests, exact runtime/planned contract checks, Alembic
upgrade/downgrade/drift and data-preservation checks, wheel resource inspection,
security checks, and full Compose API/worker/frontend/Tempo-outage acceptance.

The repository owner supplied final remote CI evidence for the exact accepted
SHA: branch `main`, trigger `push`, overall workflow conclusion `success`, duration
1 minute 28 seconds, and
[GitHub Actions run 38971960329](https://github.com/amnotwallas/sentinel/actions/runs/38971960329).
The supplied frontend Vitest detail is 2 files and 9 tests passed. Per release
instruction, this evidence was not independently retrieved. The repository's
`checks` workflow defines backend, frontend, and Compose jobs, but individual
backend and Compose job conclusions were not separately supplied. Acceptance
therefore records the owner-supplied successful workflow as aggregate remote CI
evidence and does not fabricate job-level results.

### Final acceptance decision

| Milestone 2 criterion | Accepted evidence | Status |
| --- | --- | --- |
| Definition workflows are durable through the API with change history | Integrated project, environment, test-case revision, and ordered-suite routes; complete local catalog journey and PostgreSQL acceptance | PASS |
| Future execution can pin immutable inputs without reading mutable documents | Immutable environment/test/suite revisions, exact ordered suite pins, ownership constraints, history and concurrency coverage | PASS |
| No outbound target request is sent in M2 | Contract/security review and target-I/O, DNS, and secret-resolution boundary checks; no M3 route registered | PASS |
| Persistence and migrations are reviewable and reversible | 59 real-PostgreSQL tests plus Alembic upgrade/downgrade/drift and data-preservation checks on the accepted candidate | PASS |
| Runtime OpenAPI and generated frontend client remain aligned | Exact runtime/planned contract checks and 9 frontend tests locally; supplied remote frontend Vitest result of 2 files and 9 tests passed | PASS |
| Secret references, error surfaces, logs, spans, and stored evidence remain safe | Independent M2-08 security review and synthetic-canary coverage completed without an unresolved finding | PASS |
| Integrated runtime and remote gate succeed on the accepted SHA | Full local Compose verification plus owner-supplied successful push workflow for `6b83adf0b8c9d9dcb0bba668a9e15d8ff0b4d715` | PASS |

Milestone 2 is accepted. The planning-only transition is recorded in the
[Milestone 3 handoff](../development/milestone-3-handoff.md); implementation still
requires separate authorization.

## 1. Scope and decision provenance

Accepted constraints: UUID public identities; UTC timestamps; snake_case; /api/v1 business routes; RFC 9457 problems; immutable monotonically versioned catalog revisions; exact ordered suite revision pins; strong ETags and stale If-Match => 412; explicit selectors; opt-in exact body checks; SHA-256 canonical policy fingerprints; secret references only; Sentinel-owned trace context; no outbound dispatch in M2; framework-independent domain types.

The exact shapes, numeric bounds, name equality, cursor encoding, precondition edge handling, normalizer versions/mode, document versions and sizes below close M2-00’s open wire details. They form one shared design baseline for backend, frontend and QA, rather than separate per-agent choices. Review schema diffs during each slice before publishing these as runtime compatibility surfaces. An architectural change requires a new/superseding ADR. Do not rewrite an accepted ADR to imply it originally specified these choices.

M2 includes the 16 catalog endpoints in §5 and their persistence/domain behavior in a later authorized implementation. M2 excludes authoring UI, OpenAPI import, target dispatch, execution/result routes, baseline/evaluation engines and trace reconciliation. This prerequisite task may define schemas/fixtures for those future interfaces without registering business routes or creating their persistence/workers.

Requested OpenAPI imports are addressed separately in §10 as a future local-document preview contract. MVP/ROADMAP do not include imports. Product/MVP/ROADMAP review and an ADR for material import/storage/security behavior must precede implementation. Execution requests/results in §9 are future M3–M5 contracts; documenting them does not move their implementation into M2.

## 2. Shared wire rules and bounded primitive types

Object input is closed: unknown properties are rejected; no coercion of booleans, strings and numbers. Output includes every declared field; nullable means JSON null is allowed, not that the property disappears. Optional input fields use the stated default; explicit null is rejected unless expressly nullable. Array order is significant. Duplicate JSON object keys, NaN/Infinity, invalid UTF-8 and unpaired Unicode surrogates are rejected. No client-supplied created_at, version, project_id inside nested creation bodies, active pointers, fingerprints or server IDs.

| Type | Exact representation and bounds |
| --- | --- |
| UUID | Canonical lowercase hyphenated RFC UUID string, non-nil; UUID version not restricted for reads. Server-generated identities use injectable UUIDv4. |
| Timestamp | RFC 3339 UTC, ending Z; fixed six fractional digits in server output. |
| Version | JSON integer 1..2147483647. Exhaustion returns 409 resource_conflict; never wraps. |
| StateVersion | JSON integer 1..2147483647; internal optimistic-concurrency sequence, separate from revision Version. |
| Name | NFC Unicode string, 1..120 code points after trimming outer spaces. Reject controls; preserve internal whitespace. Equality is case-sensitive after NFC/trim. |
| SHA256 | 64 lowercase hexadecimal characters, no algorithm prefix. |
| Severity | required or advisory. |
| Method | GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE. No automatic uppercase coercion. |
| VariableName | [A-Za-z_][A-Za-z0-9_]{0,63}. |
| SecretName | [A-Z][A-Z0-9_]{0,63}. |
| HeaderName | ASCII HTTP token, 1..128 bytes; normalize to lowercase in canonical stored documents/output. |
| JSONPointer | RFC 6901 string of 0..1024 UTF-8 bytes; empty points to root. Only ~0 and ~1 escapes; no URI fragment form; no automatic wildcard syntax. |
| JSONValue | null, boolean, finite JSON number, Unicode string, array, object. Maximum nesting 32, object members 256 per object, array length 1000, scalar string 65536 UTF-8 bytes; entire document limit applies. |
| JSONNumber | Decimal parsed from the original token: at most 38 significant digits and adjusted exponent -128..128; no binary-float decision. Canonical rules in §8. |
| RelativeLink | Server-generated path under /api/v1 with UUIDs and bounded server cursors only. No arbitrary operator URLs. |
| Code | Closed documented enum for its particular response; never a raw exception name/message. |
| DefinitionBytes | At most 262144 UTF-8 bytes for canonical revision document; request JSON body total at most 524288 bytes including envelope. Limits are proposed v1 compatibility limits. |

All input strings used in headers/path/query reject NUL, CR and LF. URLs reject controls, whitespace, backslash, userinfo and fragments. JSON data may contain escaped control characters as data, but never enters logs/spans. Do not globally trim body/header/query values.

Frontend mapping: UUID/Timestamp/SHA256 are branded strings or generated constrained string schemas, never numbers. Durations, versions, ordinals and counts are safe JSON integers. JSONNumber can exceed JavaScript lossless number precision: backend validates decimal tokens; frontend must preserve lossless JSON tokens for body/expected documents and fingerprint fixtures. A plain JSON.parse/stringify round trip is not the contract for high-precision values. If the frontend does not support a lossless document boundary, negotiate a narrower numeric bound in M2-00 rather than silently rounding.

HTTP bodies use application/json. Creation returns 201, Location for the created identity and ETag for the returned mutable resource. Successful update returns 200 with current detail and ETag. GET returns 200. An unsupported method returns 405; an unknown business path returns 404. Unsupported request media type returns 415 unsupported_media_type; oversized body returns 413 request_too_large; malformed JSON uses 422 validation_failed. Transport shape validation never echoes input.

API authentication remains existing Settings-based bearer protection; health stays exempt. Remote binding requires a token; no multi-user scope is introduced. CORS is deployment configuration. Domain validation is enforced again in the application service, independently of Pydantic transport parsing.

## 3. Stable problem and field-error contract

Problem fields, required: type (constant "urn:sentinel:problem:" + code), title (fixed documented safe text for code), status (HTTP integer), code (enum). Optional errors is an array 1..50 of FieldError for validation errors and is omitted for nonvalidation errors, preserving the existing M1 problem representation. No raw detail, instance path, request body, submitted value, exception dump, SQL parameters, authorization material or cursor contents.

FieldError has location (body | path | query | header), pointer (JSONPointer to fixed schema property/array index; arbitrary map keys and unknown submitted property names are replaced with "*" before serialization), code (enum below), message (fixed safe text for field code). Pointer is a schema-location hint, not a reflected value. Errors sort by location/pointer/code; retain first 50. Do not use Pydantic raw input/ctx/error messages as response text.

Exact fixed field-message strings are defined in the [planned schema](../contracts/milestone-2.openapi.json); messages use the field code with underscores replaced by spaces and its first letter capitalized. The `resource_not_found` title remains M1’s `Request failed`.

Field codes: required, type_invalid, value_invalid, extra_field, limit_exceeded, duplicate, invalid_uuid, invalid_url, invalid_json_pointer, invalid_secret_reference, secret_placement_forbidden, credential_literal_forbidden, trace_context_forbidden, unsafe_replay_acknowledgement_required, incompatible_fields, cursor_invalid.

| Top-level code | HTTP | Fixed title | Application |
| --- | --- | --- | --- |
| validation_failed | 422 | Request validation failed | Shape, URL, document, limits, pointer, cursor, forbidden literal/context, malformed header syntax |
| secret_reference_invalid | 422 | Secret reference invalid | Invalid tagged-name/shape/placement; if any validation error is a secret-reference error this is the top-level code |
| resource_not_found | 404 | Request failed | Missing/deleted identity; membership missing or outside requested project; never enumerate another project |
| revision_conflict | 412 | Revision conflict | Current strong ETag does not match the supplied valid strong value |
| revision_precondition_required | 428 | Revision precondition required | Missing If-Match on an update; proposed additive code |
| resource_conflict | 409 | Resource conflict | Live-project name conflict or version exhaustion; proposed additive code |
| request_too_large | 413 | Request too large | Input envelope byte cap; proposed additive code |
| unsupported_media_type | 415 | Unsupported media type | Input not application/json; proposed additive code |
| authentication_required | 401 | Authentication required | Existing bind/token contract |
| forbidden_origin | 403 | Forbidden origin | Existing origin contract |
| idempotency_conflict | 409 | Idempotency conflict | Future execution key/payload mismatch |
| baseline_ineligible | 409 | Baseline ineligible | Existing future baseline contract |
| baseline_incompatible | 409 | Baseline incompatible | Existing future baseline contract |
| internal_error | 500 | Internal server error | Existing safe unexpected-error boundary |
| http_error | status 405 | Request failed | Existing fallback; document Allow header without reflecting input |

Authentication is checked before business parsing. After authenticated parsing: validate request shape, obtain resource in requested scope, require/parse precondition, then enter locked service transaction and compare current state. Stale updates and failed validation perform no revision, pointer, version, change-event or metadata write.

New additive codes/statuses are specified here; the coordinator adds their schemas to runtime OpenAPI only when the corresponding slice is implemented. Existing code only provides generic safe problems; it does not implement these extensions.

## 4. Pagination and concurrency

### Pagination

All lists accept limit (optional strict integer 1..100, default 50) and cursor (optional string, 1..2048 ASCII bytes; default absent; null not accepted). Other query fields are rejected unless a route explicitly declares them. Responses are {items: [...], next_cursor: string|null}; both fields required. No total or offset.

Catalog identity lists sort ascending (created_at, id). Test revision history sorts ascending (version, id). A cursor is opaque to clients; implementation v1 is unpadded base64url of canonical JSON with exact fields: cursor_version=1; resource_kind enum projects|environments|test_cases|test_case_revisions|suites|executions; scope_id UUID|null; filter_fingerprint SHA256; after containing either created_at Timestamp plus id UUID, or version Version plus id UUID. Enforce decoded byte cap 1536, closed shape, exact route/scope/filter match and corresponding sort form. Reject wrong scope, malformed/tampered shape, unknown version or unsupported cursor as 422 validation_failed with cursor_invalid. Never execute cursor contents as SQL. No signing secret is required: decoded values are revalidated and scoped, and convey no permission.

filter_fingerprint is SHA256 of canonical route filters excluding cursor and limit; a changed limit may continue the same cursor. For empty filters hash canonical {}. Cursors expose only public IDs/times/versions and their hashes, not definition values or credentials. Read-committed keyset pagination has no cross-request snapshot guarantee; immutable sort keys prevent duplicates from updates. A concurrent insertion that sorts before the cursor may not be visited; this limitation is documented, not a promise of a snapshot.

Response cap for catalog lists is 1048576 encoded UTF-8 bytes. Stop before the next item would exceed either count or byte limit; provide next_cursor after the last emitted item. A single revision is below this cap by DefinitionBytes; never return an empty page with a continuation when a valid next item exists.

### ETag/If-Match

Project/environment/test/suite detail and creation/update responses return one strong ETag; list envelopes carry no mutable-resource ETag. v1 token is quoted "<resource_kind>:<uuid>:<state_version>". Clients treat it as opaque. state_version increments for every committed metadata/pointer change, including environment metadata-only rename; representation serialization and links are deterministic for a given version. Revision IDs/versions remain separate.

PATCH environment and PUT test/suite require exactly one strong quoted If-Match token. Missing => 428 revision_precondition_required. Invalid syntax, weak token, wildcard or multiple comma-separated tokens => 422 validation_failed at header /if-match. A syntactically valid other-resource or stale token => 412 revision_conflict. GET of an immutable revision history element does not authorize updates; there are no immutable-resource mutation routes. POST creation does not require If-Match because the created identity does not yet exist; supplied If-Match on creation is rejected as 422 incompatible_fields. No If-None-Match/304 support is proposed for v1.

Inside one transaction lock/CAS the owning stable identity, compare the expected state_version, allocate next revision number, insert immutable document and safe ChangeEvent, activate its pointer, update metadata/state_version/time, commit. Never allocate next version as an unlocked MAX(version)+1. Database uniqueness (owner_id,version), owner/project FKs and pointer-owner consistency reinforce the service invariants. Two simultaneous writers with one ETag have one success and one 412; the loser adds no history. PUT retries after success with the old ETag are 412; there is no definition idempotency-key feature.

## 5. M2 catalog route and entity contracts

Only these routes implement M2 catalog scope. No project PATCH/delete, separate environment/suite revision-history, global change-history, import or execution route is added by this proposal.

| Route | Request | Response |
| --- | --- | --- |
| GET /api/v1/projects | ListQuery | Page[Project] |
| POST /api/v1/projects | ProjectCreate | Project, 201 |
| GET /api/v1/projects/{project_id} | UUID | Project |
| GET /api/v1/projects/{project_id}/environments | UUID, ListQuery | Page[EnvironmentSummary] |
| POST /api/v1/projects/{project_id}/environments | UUID, EnvironmentCreate | EnvironmentDetail, 201 |
| GET /api/v1/environments/{environment_id} | UUID | EnvironmentDetail |
| PATCH /api/v1/environments/{environment_id} | UUID, If-Match, EnvironmentPatch | EnvironmentDetail |
| GET /api/v1/projects/{project_id}/test-cases | UUID, ListQuery | Page[TestCaseSummary] |
| POST /api/v1/projects/{project_id}/test-cases | UUID, TestCaseWrite | TestCaseDetail, 201 |
| GET /api/v1/test-cases/{test_case_id} | UUID | TestCaseDetail |
| PUT /api/v1/test-cases/{test_case_id} | UUID, If-Match, TestCaseWrite | TestCaseDetail |
| GET /api/v1/test-cases/{test_case_id}/revisions | UUID, ListQuery | Page[TestCaseRevision] |
| GET /api/v1/projects/{project_id}/suites | UUID, ListQuery | Page[SuiteSummary] |
| POST /api/v1/projects/{project_id}/suites | UUID, SuiteWrite | SuiteDetail, 201 |
| GET /api/v1/suites/{suite_id} | UUID | SuiteDetail |
| PUT /api/v1/suites/{suite_id} | UUID, If-Match, SuiteWrite | SuiteDetail |

ProjectCreate: name Name required; no description/settings fields. Project output: id UUID, name Name, created_at Timestamp, deleted_at Timestamp|null (always null in M2; deletion not implemented). Live project names unique after Name normalization. Each stable environment/test/suite identity output has id UUID, project_id UUID, name Name, active_revision_id UUID, created_at Timestamp, updated_at Timestamp. Identity summaries add active_revision_version Version and exclude full documents. Name uniqueness for environments/test/suites is not imposed: identities distinguish equal display names, and the accepted architecture only mandates project-name uniqueness.

EnvironmentCreate: name Name required; definition EnvironmentDocument required. EnvironmentPatch: name Name optional, definition EnvironmentDocument optional; at least one must be present; no nullable deletion/merge form. A provided definition replaces the entire environment document and creates/activates version n+1 even when canonically equal. A name-only PATCH increments metadata state_version and records a safe change event, but creates no revision. Empty PATCH => 422. Same-name-only PATCH still records the explicit edit and increments state_version; do not silently elide it.

EnvironmentDetail: stable identity fields plus active_revision EnvironmentRevision. EnvironmentRevision: id UUID, environment_id UUID, version Version, schema_version integer literal 1, definition EnvironmentDocument, created_at Timestamp. EnvironmentDocument fields:
- schema_version: integer literal 1, input default 1;
- base_url: absolute http/https URL, 1..2048 UTF-8 bytes, required; IDNA host normalized lowercase, IPv6 canonical; no userinfo/query/fragment/template. Path prefix allowed, normalized to trailing slash; no dot segments. Default ports removed;
- variables: map VariableName -> string 0..4096 UTF-8 bytes, maximum 128 entries, default {}; nonsecret only; no $secret tags or recursive templating;
- secret_references: array of exact SecretReference objects, maximum 128, default []; unique SecretName; optional descriptive declarations only, never values/resolved status; see decision note below;
- target_policy: TargetPolicy, default its complete canonical defaults.

Secret declarations resolve of the architecture statement that EnvironmentRevision contains references while variable values remain nonsecret. They are descriptive names, not grants, aliases, value enumeration or a prerequisite to test-case reuse. The worker still resolves a request's direct SecretName; an undeclared reference is not silently denied. Backend and frontend use this exact declaration shape; a change requires a coordinated contract revision. Do not invent alias or secret-template substitution.

TargetPolicy: schema_version integer literal 1 default 1; allowed_hostnames string[] max 128 default []; allowed_cidrs string[] max 128 default []; denied_hostnames string[] max 128 default []; denied_cidrs string[] max 128 default []; allowed_ports strict integer[] 1..65535 max 128|null default null. Hostnames are exact lowercase ASCII IDNA names (no wildcard, port, URL, trailing dot or template); IP literals are represented as canonical /32 or /128 CIDRs. CIDRs parse strictly with no host bits; all lists reject duplicates and canonical sort by value. null ports means inherit deployment policy, not bypass it; nonnull set may only narrow deployment-permitted ports. Deployment denies cannot be weakened; initial/hop DNS/address checks remain worker-only. Environment/deployment explicit allow exceptions permit intentional private testing; any explicit deny wins. Accepted blocked address classes are never editable boolean switches. M2 checks syntax only, so a stored target is not a statement that the later worker will permit it.

TestCaseWrite: name Name required; definition TestDefinition required; unsafe_replay_acknowledgement nullable literal string "duplicate_effects_possible", optional default null. If definition.allow_unsafe_replay=true, explicit acknowledgement must be supplied on every create/PUT; otherwise acknowledgement must be null/absent. It is command consent, not part of comparison fingerprint, not an automatic HTTP retry count. Revision stores allow_unsafe_replay plus server-recorded consent metadata (acknowledged_at Timestamp|null, acknowledgement literal|null) for audit, with no user/account identity.

TestCaseDetail: stable identity fields plus active_revision TestCaseRevision. TestCaseRevision: id UUID, test_case_id UUID, version Version, schema_version integer literal 1, definition TestDefinition, policy_fingerprint SHA256, unsafe_replay_acknowledged_at Timestamp|null, created_at Timestamp. The original document carries allow_unsafe_replay; response must not duplicate contradictory booleans. A valid PUT always creates version n+1, updates name/pointer atomically and records one change event.

SuiteWrite: name Name required; test_case_revision_ids UUID[] required, 1..100 entries, ordered; no null; no active-case resolution shortcuts. Validate every revision exists within the suite's project. One test case appears at most once, even when different revisions of that case are supplied, matching "unique case membership." Empty/duplicate lists => 422 validation_failed; missing/cross-project membership => 404 resource_not_found. A valid PUT creates version n+1 even for canonically identical content.

SuiteDetail: stable identity fields plus active_revision SuiteRevision. SuiteRevision: id UUID, suite_id UUID, version Version, schema_version integer literal 1, items SuiteRevisionItem[] 1..100, created_at Timestamp. Item: ordinal strict integer 0..99, test_case_id UUID, test_case_revision_id UUID, test_case_revision_version Version; all required. Ordinals are assigned from input order as 0..n-1, contiguous. test_case_id/version are server-derived convenience fields; persistence membership identity is the exact revision FK, not a copied mutable definition.

ChangeEvent is append-only internal evidence in M2; no new public history route. Future wire output: id UUID, project_id UUID, kind enum environment_created|environment_updated|test_case_created|test_case_revised|suite_created|suite_revised|baseline_activated, subject_type enum environment|test_case|suite|baseline, subject_id UUID, before_ref UUID|null, after_ref UUID|null, summary {changed_fields: string[] max 16 from a fixed enum}, created_at Timestamp. Fixed changed_fields vocabulary: name, base_url, variables, secret_references, target_policy, request, assertions, comparison_policy, redaction, allow_unsafe_replay, suite_items, baseline_activation. No raw names, variable keys/values, URL/query/header/body, free text or literal expected value goes into summary. Metadata-only edits may have the same before/after revision reference; state_version change is held on the identity. No project creation event is required by accepted MVP scope.

## 6. Exact test-definition document

TestDefinition fields: schema_version literal 1 default 1; request Request required; assertions Assertion[] 0..128 default []; comparison_policy ComparisonPolicy default its complete defaults; redaction Redaction default complete defaults; allow_unsafe_replay strict boolean default false. There is no arbitrary script, imported schema assertion, extra authentication object, snapshot inference or trace-context override.

Request fields:
- method Method, required;
- path string, required, 1..2048 UTF-8 bytes; begins / but not //; no absolute authority, query, fragment, backslash, control or dot-segment path. Combine with base_url path prefix by removing path's first slash; it cannot replace authority;
- query array QueryParameter max 128 default []; each {name: string 1..128 UTF-8 bytes, value: string 0..4096 UTF-8 bytes}; repeated names permitted and array order preserved; references forbidden;
- headers array Header max 64 default []; each {name: HeaderName, value: string 0..8192 UTF-8 bytes | SecretReference}; duplicate normalized names rejected; header aggregate byte cap 32768. Reject transport-managed host, content-length, transfer-encoding, connection, upgrade, proxy-connection, trailer, te and expect headers as validation_failed/value_invalid; the future HTTP adapter owns authority/framing and unsupported upgrades;
- body Body|null default null; Body closed tagged union {kind:"json", value:JSONValueWithSecretLeaves} or {kind:"text", value:string 0..131072 UTF-8 bytes}; no body/header/query "secret interpolation" string syntax;
- timeout_ms strict integer 1..120000 default 30000 (total timeout; deployed maximum may lower this);
- connect_timeout_ms strict integer 1..120000 default 5000, <= timeout_ms;
- read_timeout_ms strict integer 1..120000 default 10000, <= timeout_ms;
- follow_redirects boolean default false;
- max_redirects integer 0..3 default 3; worker obeys 0 when redirects disabled regardless stored maximum;
- verify_tls boolean default true; false is explicit opt-out, permitted only by an operator deployment policy decided/documented before M3; M2 static validation cannot claim TLS safety;
- max_response_bytes integer 1..1048576 default 262144; deployment maximum may lower it.

When timeout_ms is explicitly smaller than default connect/read values, caller must supply compatible subordinate values; do not silently clamp policy. A JSON body and text body are mutually exclusive. Content-Type can be explicitly supplied; if absent the future adapter uses application/json for JSON and text/plain; no M2 outbound adapter is added.

Template grammar is exactly {{variables.<VariableName>}} in path/query/header text/text body/ordinary JSON string leaves. No expressions, filters, recursion, secret namespace, nested object lookup, dynamic variable name, base_url templating or numeric type coercion. Undefined variables fail future preparation before dispatch, not testcase creation (one case is usable across environments). Path substitutions are percent-encoded as path-segment data; query substitutions are encoded by the query adapter; header substitutions reject CR/LF after expansion. JSON string expansion remains a JSON string. Malformed braces/template syntax => 422. Literal non-template braces in JSON/text remain ordinary content.

SecretReference is a closed object containing only "$secret": SecretName. A tag occupies an entire header value or JSON-body leaf; no prefix/suffix concatenation. Header secret contains its complete wire value, including Bearer prefix when needed. Any object with a $secret property must satisfy this exact shape; additional fields or nested/tag-name values => secret_reference_invalid. No secret reference in path/base URL/query/variables/assertions/policy/redaction/text body/baggage. Definitions and reads never call process/mounted-secret resolution or test existence.

Fixed credential names: authorization, proxy-authorization, cookie, set-cookie, x-api-key plus deployment-configured variants. A request value for those names must be SecretReference; a string literal or nonsecret variable template is rejected. This protection is case-insensitive and cannot be disabled by redaction options. Other arbitrary secrets typed as literals cannot be reliably detected; document user responsibility. Reference names are permitted in definition responses, resolved values are never permitted in responses/persistence/logs/spans. Stored nonsecret literal bodies/expected values are not an encrypted secret store.

Reject traceparent and tracestate headers case-insensitively. Permit one unrelated baggage header as a literal bounded 4096 ASCII bytes, at most 32 W3C members; names unique; values percent-encoding must be valid; reject decoded keys sentinel.execution.id and sentinel.attempt.id under a conservative case-insensitive comparison, malformed members/controls, secret tags and templates. Do not reject all baggage, invent custom correlation headers or resolve baggage from a secret. Enforce aggregate request-header size as well.

Redaction: schema_version literal 1 default 1; json_pointers JSONPointer[] max 128 default []; header_names HeaderName[] max 128 default []; duplicates rejected and canonical sorted. These add to fixed response/header redaction; omission does not disable fixed protections. The v1 pointers apply to captured response JSON. A pointer root "" redacts the entire body. Comparison against redacted/unavailable evidence cannot fabricate a pass: later evaluation uses the documented inconclusive/error behavior. Do not silently remove configured selectors. Request secret tags are independently protected.

## 7. Assertions, selectors and normalizers

Every Assertion/Selector includes id UUID required, stable across retained edits; IDs are unique across the revision's rule collections. Client/import draft author must generate these with a UUID facility; the API does not accept ad-hoc numeric IDs or overload test/attempt IDs. Each has severity Severity required. Body/expected values obey JSONValue and DefinitionBytes; no secret tags.

Assertion is exactly one closed tagged form:
- {id,severity,kind:"status_code", expected_codes:integer[1..100] with unique values 100..599}; membership in configured list, no range DSL.
- {id,severity,kind:"header_present", header_name:HeaderName};
- {id,severity,kind:"header_equals", header_name:HeaderName, expected:string 0..8192 UTF-8 bytes}; case-insensitive name, exact value; reject equality against fixed credential-header names because expected secrets must not be persisted.
- {id,severity,kind:"json_present", pointer:JSONPointer};
- {id,severity,kind:"json_absent", pointer:JSONPointer};
- {id,severity,kind:"json_type", pointer:JSONPointer, expected_type:"null"|"boolean"|"number"|"string"|"array"|"object"};
- {id,severity,kind:"json_equals", pointer:JSONPointer, expected:JSONValue};
- {id,severity,kind:"text_equals", expected:string 0..131072 UTF-8 bytes}; explicit opt-in, for non-JSON content; no whitespace/newline normalization.

Presence distinguishes absent from JSON null. JSON booleans are not numbers; array order matters; object key order does not. Rule evaluation and normalization are M4 work; M2 validates/stores only.

ComparisonPolicy fields: schema_version literal 1 default 1; selectors JSONSelector[] max 128 default []; exact_text_body boolean default false; text_body_selector TextSelector|null default null; performance_threshold_ms strict integer 1..120000|null default null. JSON and complete-text baseline selectors cannot coexist in v1 (content expectations differ); exact_text_body=true requires nonnull text_body_selector and selectors=[]; false requires text_body_selector=null. Performance is absolute integer milliseconds and advisory; changing it changes this exact policy fingerprint, as the accepted contract requires exact policy compatibility.

JSONSelector: {id:UUID,severity:Severity,pointer:JSONPointer,normalizer:Normalizer}; all required except normalizer default none-v1. Reject duplicate pointers; preserve selector order. TextSelector: {id:UUID,severity:Severity}; no text normalizer. No default baseline selectors, volatile-field heuristics, automatic body snapshot or baseline values in the definition.

Normalizer closed union:
- {name:"none", version:1};
- {name:"sort_scalar_array", version:1};
- {name:"round_decimal", version:1, scale:strict integer 0..12, rounding:"half_even"}; rounding required, no hidden runtime-global mode.

none is identity. sort_scalar_array accepts homogeneous null/boolean/number/string JSON scalar arrays only, rejects mixed types and nested containers; numeric order uses Decimal, strings order by Unicode scalar values, booleans false before true, null arrays unchanged. round_decimal accepts JSON number only (not numeric strings/bools), quantizes Decimal to explicit scale with ROUND_HALF_EVEN. Invalid inputs are explicit later evaluation errors, never coercion. These precise comparator semantics are proposed closure of ADR 0003's unspecified rounding mode, and must be reviewed before M4 implementation.

## 8. Canonical serialization and compatibility

Canonicalize a validated definition by materializing all defaults, normalized header names/hostnames/CIDRs, and explicit schema/normalizer versions. Reject duplicates before canonicalization. Sort object keys by Unicode scalar value; preserve array order except explicitly defined set-like target/redaction lists. No Unicode normalization of ordinary JSON strings/keys (Name alone is NFC); no silently rewriting body data. Emit UTF-8, no spaces, no insignificant escaping, JSON-required escapes only.

Parse JSON numeric tokens as Decimal. Canonical numeric token is plain base-10, no exponent, no leading "+", no unnecessary trailing fractional zeros; negative zero becomes 0; at least one digit before decimal point. Canonical string encoding escapes quote/backslash/control characters; other Unicode emitted directly. Bounded exponent prevents expansion beyond document cap. Parser/canonicalizer fixtures must include 1, 1.0, 1e0 equivalence, negative zero, large decimals, booleans, mixed scalar arrays, Unicode and reordered objects; no float intermediate.

policy_fingerprint = lowercase SHA-256 hex over canonical UTF-8 bytes of the complete ComparisonPolicy, including schema/normalizer versions, selector IDs/order/severity, exact-text configuration and performance threshold. UI metadata is not accepted in this closed policy and is therefore never hashed. Assertions/request/name/redaction/replay policy are outside this policy hash. Request-only edits must preserve it; selected policy changes must change it. A client must retain rule IDs for request-only changes.

Do not reuse this policy hash as a request fingerprint, revision ETag or import identifier. A future dispatch request fingerprint replaces resolved secret values with reference name plus fixed placeholder; M2 never resolves a value to compute a hash.

Revision immutability is canonical semantic/serialized document immutability, not preservation of original HTTP whitespace/key insertion order; PostgreSQL JSONB cannot preserve that source encoding. JSONB documents carry schema_version and canonical values; relational IDs/FKs/versions/activation remain columns. Preserve redaction as an explicit persisted revision section even though the abbreviated architecture entity table omitted its field.

## 9. Future execution request and result contracts (schemas only now)

### Creation request and list filters

POST /api/v1/executions request is closed {environment_id:UUID required, test_case_id:UUID optional, suite_id:UUID optional}; exactly one case/suite field must be present and nonnull. No request document, target URL, active revision override, baseline override, per-run unsafe replay toggle or transport retry count. Validate ownership and resolve all immutable pins inside one transaction with execution/items/job/idempotency record. A suite uses its pinned case revisions, never current active test pointers.

Optional Idempotency-Key: ASCII visible string 1..128 bytes, no whitespace/controls; key is installation-scoped for 24 hours. Hash raw key at rest; hash canonical payload with one chosen source and environment. Equal key/payload returns the original 202 ExecutionDetail and Location; different payload =>409 idempotency_conflict; expired key may create a new execution. Serialize concurrent key claims transactionally. No missing-secret/target-DNS lookup during asynchronous creation.

GET /api/v1/executions list filters: project_id, environment_id, test_case_id, suite_id optional UUID; status optional ExecutionStatus; verdict optional Verdict; created_from/created_before optional Timestamp with inclusive lower/exclusive upper bound and from<before. case and suite filters mutually exclusive. All filters encoded in cursor fingerprint. Sort ascending(created_at,id) as catalog lists. Page[ExecutionSummary] with ListQuery. Referenced nonexistent filter returns empty list unless a requested project scope is missing/deleted (404); no exposure of foreign project contents.

### Enumerations

ExecutionStatus: queued, running, completed, failed.
ItemStatus: pending, running, completed, indeterminate, failed, skipped.
AttemptState: prepared, dispatching, response_received, evaluated, replay_scheduled, indeterminate, failed.
Verdict: passed, functional_regression, performance_warning, observed_change, inconclusive, baseline_required, not_evaluated.
TraceStatus: pending, missing, available, partial, tempo_unavailable, expired.
TransportOutcome: response_received, dns_failure, connect_timeout, read_timeout, total_timeout, tls_failure, connection_failure, target_denied, redirect_denied, response_limit_exceeded, indeterminate; bounded stable enum, no raw socket/driver errors.
EvaluationOutcome: passed, failed, unevaluable, not_evaluated.
BodyKind: json, text, omitted.
CorrelationSource: sentinel_context, baggage_attribute_search.
TraceRelation: primary, linked.

EvaluationOutcome/TransportOutcome are proposed wire vocabulary, not existing domain implementations. Required invalid-JSON assertion yields failed with invalid_json; missing/truncated/redacted required content yields unevaluable/inconclusive rather than fabricated equality. Invalid normalizer input is an explicit evaluation error; its mapping to the later evaluation/verdict contract needs M4 review and is not decided here. Resolve any divergence from accepted classification through M4 review.

### Exact output models

All fields below required, nullable where noted; max 100 execution items (suite definition bound). Collections are ordered (items ordinal; attempts sequence then ID; evaluations original configured rule order; references primary first then ID). Future result-detail encoded response limit 8388608 bytes; history lists 1048576 bytes; attempt artifacts remain independently bounded by deployment capture limit. No unbounded full request or full trace is returned.

ExecutionSummary:
id UUID; project_id UUID; environment_id UUID; environment_revision_id UUID; source_type test_case|suite; source_id UUID; source_revision_id UUID; status ExecutionStatus; verdict Verdict|null; created_at Timestamp; started_at Timestamp|null; finished_at Timestamp|null; item_count integer 1..100; completed_item_count integer 0..100; links {self:RelativeLink}.
No captured bodies, resolved request, evaluations or job counters in history summaries. item_count is the materialized count; completed_item_count counts terminal completed/indeterminate/failed/skipped items, so it describes progress, not functional passes.

ExecutionDetail extends Summary with:
items ExecutionItem[] 1..100;
change_evidence ChangeEvent[] 0..128 (safe chronological evidence only, no root-cause claims);
change_evidence_truncated boolean;
A queued response already contains all immutable pin IDs and materialized items.

ExecutionItem:
id UUID; ordinal integer 0..99; test_case_id UUID; test_case_revision_id UUID; test_case_revision_version Version;
status ItemStatus; verdict Verdict|null; started_at Timestamp|null; finished_at Timestamp|null;
attempts AttemptSummary[] 0..100; attempts_truncated boolean; attempt_count integer >=0. When the count exceeds 100, summaries show the latest 100 in sequence order and set attempts_truncated=true; their count and identities remain explicit. A future paginated attempt-history route requires product/contract review before such a limit can be reached in a supported runtime.
HTTP attempt sequence and queue delivery count have independent types and semantics. No wire bound is inferred from the current queue delivery default; re-delivery can resume without sending. An ordinary item is sent once; any replay requires the accepted policy and fresh identifiers.

AttemptSummary:
id UUID; sequence integer 1..2147483647; state AttemptState; verdict Verdict|null;
created_at Timestamp; dispatch_recorded_at Timestamp|null; response_recorded_at Timestamp|null; finished_at Timestamp|null;
duration_ms integer 0..9007199254740991|null; transport_outcome TransportOutcome|null;
primary_trace_id 32 lowercase nonzero hex|null; client_span_id 16 lowercase nonzero hex|null;
replayed_by_attempt_id UUID|null; included_in_verdict boolean; links {self:RelativeLink}.
IDs are null only before dispatch/checkpoint or preparation failure, never fabricated from execution/attempt UUIDs. Replays receive new attempt/trace/span; replay_scheduled predecessor remains visible but is excluded once its successor evaluates. A recorded response/checkpoint does not guarantee full telemetry.

GET /api/v1/attempts/{attempt_id} returns AttemptDetail, extending Summary with:
execution_id UUID; execution_item_id UUID; request_fingerprint SHA256|null;
preparation_error_code null|secret_missing|template_variable_missing|target_policy_denied|request_invalid|infrastructure_failure;
observation ResponseObservation|null;
baseline_comparison BaselineComparison;
evaluations Evaluation[] 0..257 (128 assertions+128 selectors+one performance evaluation);
trace_references TraceReference[] 0..33 (one primary plus at most 32 linked);
trace_references_truncated boolean.
No raw/final outbound request is returned.

ResponseObservation:
id UUID; status_code integer 100..599|null;
headers array {name:HeaderName,value:string 0..8192 UTF-8 bytes} max64 and 32768 aggregate bytes (redacted first);
body_kind BodyKind; body string|null (at most1048576 UTF-8 bytes after redaction/capture); captured_bytes integer 0..1048576;
truncated boolean; redaction_unavailable boolean; recorded_at Timestamp; expires_at Timestamp.
body=null when omitted; kind=json returns serialized redacted JSON as a string and kind=text returns decoded redacted text. A JSON null body is the string "null" with kind=json. The string boundary preserves arbitrary captured decimal tokens without JavaScript numeric rounding; DefinitionBytes/definition-number limits do not apply to captured body data. Fixed and configured sensitive header values are replaced with the constant [REDACTED]; retain a validated normalized name, never its original value. Header/body output byte caps apply after redaction; captured_bytes measures source bytes accepted by the bounded capture, not the redacted serialization length. When JSON redaction cannot safely parse required paths, omit entire body and set redaction_unavailable=true; do not return unsafe fallback. Expired artifact => observation=null; metadata explains expiration through observation_state below.

Add AttemptDetail observation_state enum not_recorded|available|expired|omitted as required. expired distinguishes expired retained detail from no dispatch/response; omitted means response recorded but no safe artifact body, not successful body evaluation.

BaselineComparison:
state enum not_requested|pending|missing|incompatible|compatible; baseline_id UUID|null; baseline_version Version|null; policy_fingerprint SHA256|null; checked_at Timestamp|null.
No selectors means not_requested with null reference fields; configured selectors before lookup mean pending. missing has no reference; incompatible/compatible require all three reference fields and checked_at. This records the immutable candidate actually inspected, not whatever baseline is active when the UI later reads the result. compatible means policy compatibility, not selector success.

Evaluation:
id UUID; kind assertion|baseline_selector|performance; rule_id UUID|null (null only for policy-level performance threshold);
severity Severity (performance advisory); outcome EvaluationOutcome; message_code enum assertion_passed|status_mismatch|header_missing|header_mismatch|json_missing|json_unexpected|json_type_mismatch|json_value_mismatch|text_mismatch|invalid_json|normalizer_input_invalid|baseline_missing|baseline_incompatible|selected_value_mismatch|duration_exceeded|content_truncated|content_redacted|not_evaluated;
expected JSONValue|null; actual JSONValue|null; evidence_omitted boolean.
Bound each expected/actual canonical serialized value to4096 bytes; larger/redacted/unavailable =>null with evidence_omitted=true, never a raw excerpt. A null selected value versus omitted evidence is distinguished by the boolean and message code. No arbitrary human/exception message.

TraceReference:
id UUID; relation TraceRelation; trace_id 32 lowercase nonzero hex; span_id 16 lowercase nonzero hex|null (primary requires nonnull);
correlation_source CorrelationSource; status TraceStatus;
first_checked_at Timestamp|null; last_checked_at Timestamp|null; deadline_at Timestamp|null (null before the attempt becomes terminal; once terminal, default terminal timestamp plus60000 milliseconds);
last_error_code null|tempo_unavailable|trace_not_found|client_span_missing|context_incomplete|lookup_expired;
tempo_url string|null max2048, generated solely from deployment-configured http/https UI origin (no userinfo/query/fragment) plus validated trace ID and a fixed reviewed link pattern; never operator request input. Null when UI integration is unconfigured or the trace is not navigable.
One primary per dispatched attempt; linked-only evidence does not make missing primary context complete. Correlation retries/state never change functional verdict; do not expose trace retries as queue or HTTP attempt counters.

### Execution contract blockers

Accepted attempt state graph has no explicit transition for a recorded transport failure without HTTP response; M3 must define the durable observation checkpoint/transition consistently. Proposed result vocabulary does not authorize adding a state silently.

First-baseline bootstrap is currently contradictory/incomplete: ADR0004 makes baseline_required attempts ineligible, while required selectors without an active baseline yield baseline_required. No route imports trusted expected baseline values, so first promotion for a required-selector case has no documented source path. Do not solve this through M2 schemas or automatic promotion; resolve with product decision/ADR before M4.

Baseline selection time (queue creation versus preparation/evaluation) is unspecified; settle it in M3/M4 and persist the actual immutable baseline candidate reference. Never let a later UI read silently substitute a new activation. The BaselineComparison result shape does not itself pick the selection time.

duration_ms measures the network interval in integer milliseconds, not queue wait. It is not capped at the configured timeout: scheduling and cleanup can extend observed elapsed time. It never participates in binary floating-point comparison.

## 10. Future bounded OpenAPI import preview contract (no business routes)

Purpose: inspect an operator-provided local JSON OpenAPI document and return reviewable definition proposals. No URL fetching, YAML processing, external $ref, credential discovery, request dispatch, persistence, automatic activation or baseline learning. No endpoint is registered now; schemas can be fixtures/components. A future route name and apply command require explicit product/ADR review.

Input ImportPreviewRequest, closed:
schema_version literal1 default1;
document ImportJSONValue required, root object, encoded UTF-8 max1048576 bytes, max depth32, max50000 total nodes; ImportJSONValue is JSON-native with finite numeric tokens at most128 bytes, no duplicate keys or unpaired surrogates; source document uses import limits rather than DefinitionBytes/definition-specific decimal bounds;
selected_operation_ids SHA256[] max100 default[] (empty requests an operation inventory only);
name_prefix Name|null defaultnull.
No target URL/project/environment/secret values/remote reference URL/upload path. Input is already supplied data, not a path the server opens.

Supported source: OpenAPI openapi field "3.0.x" with x0..3 or "3.1.x" with x0..1; require info object and paths object; reject Swagger2/unknown versions, malformed structure, duplicate object keys and unsupported required structures with safe validation errors. Bound paths200, supported operations200, parameters128 per operation, local refs1000, dereference depth32; cycle => issue, no infinite expansion. Resolve only JSONPointer-fragment references beginning "#/" within the supplied document; external, file, HTTP, relative and dynamically resolved references are unsupported. Never fetch them, even if operator supplies an allowlist.

Ignore all servers, securitySchemes, security values, examples, example, defaults, descriptions, summaries, extensions and inferred response baselines for proposal generation. They cannot supply credentials, target origin, asserted expected values or automatic trusted data. OperationId is display metadata only; use no raw spec description in errors/logs. Never persist the original document or dump it in validation output/spans.

Operation identity = SHA256 of canonical {method:Method,path:source path string}. This is a preview selection token, not a public resource UUID or authorization token. Normalize header/HTTP method, not operator path data; reject unsupported path shapes with an issue. Duplicate same method/path impossible in a valid closed source map. Sort inventory by path Unicode order then fixed Method enum order for deterministic output. Unknown selected token =>422 validation_failed without echoing token.

Output ImportPreview, all fields required:
schema_version literal1;
source_format literal"openapi";
source_version supported source string;
operations ImportOperation[] max200;
drafts ImportDraft[] max100;
issues ImportIssue[] max100;
issues_truncated boolean;
review_required literaltrue;
persisted literalfalse.
Encoded result max2097152 bytes; fail safely rather than partial undocumented truncation if draft/inventory size exceeds cap.

ImportOperation:
operation_id SHA256; method Method; path string1..2048 UTF-8 bytes; supported boolean; selectable boolean.
Unsupported method is represented only as an issue with schema-location hint, not as an invented Method value. Unsupported method inventory entries are omitted; selection cannot target them. A selectable operation may still require configuration before its draft is executable.

ImportDraft:
operation_id SHA256; name Name (prefix plus method/path-derived bounded name, reject rather than silently collide/trim; no imported descriptions);
definition TestDefinition;
required_variables VariableName[] max128;
required_configuration enum[] subset of request_body|credential_reference|parameter_mapping;
ready_for_creation boolean (true only when configuration list empty, but review_required stilltrue). Every selected operation either has a draft or a fatal ImportIssue explaining why no valid draft was generated.
Preview UUID rule IDs are generated by injected UUID factory; do not create test/revision UUIDs. Empty assertions/comparison selectors remain empty: OpenAPI response declarations are not explicit user-chosen regression assertions.

Mapping: retain method and safe relative route path; convert required path "{name}" to "{{variables.<name>}}" only if its exact parameter name already matches VariableName; otherwise add parameter_mapping issue/requirement and do not fabricate a lossy alias. Required path/query/header simple primitive parameters produce variable placeholders, except fixed credential headers become explicit credential_reference requirements and are not populated as literals. Optional query/header parameters omitted. Ambiguous serialization, content negotiation, arrays/objects, cookie parameters and unresolved references yield configuration issues; do not guess style/explode semantics. Request-body-required operations get request_body requirement and body=null rather than invented sample data. Declared auth requirements only set credential_reference requirement; no imported token/security default is emitted. Required configuration means ready_for_creation=false; reviewer must supply it through ordinary later catalog commands.

ImportIssue:
operation_id SHA256|null;
severity warning|error;
code enum unsupported_source_version|document_shape_invalid|document_limit_exceeded|external_reference_forbidden|reference_cycle|reference_missing|unsupported_method|unsupported_parameter|parameter_mapping_required|request_body_required|credential_reference_required|unsupported_serialization|unsafe_path|name_limit_exceeded;
location {section: root|paths|parameters|request_body|references, operation_index:integer0..199|null, parameter_index:integer0..127|null};
message fixed safe text per code.
No reflected $ref URI, description, example, parameter value, body, token, raw validation ctx or dynamic spec-property pointer is returned. Paths intentionally returned as operator-reviewed draft definitions may contain arbitrary literals the tool cannot recognize as secrets; do not assert comprehensive secret detection. No auto-apply/import persistence command is defined or authorized here.

Potential source parsing limits are schema proposal only; no source importer implementation is part of current prerequisite or M2. Before future implementation decide source licensing, raw-source disposal, review/apply consistency, deterministic selection snapshots, atomic batch creation, user acknowledgement and scope limits in product docs/ADR. Preview does not silently modify the accepted execution/assertion semantics.

## 11. Ownership, dependency handoffs and required examples

Pydantic v2 schemas live only under sentinel.api (transport) and sentinel.config (configuration); use strict validators/closed schemas. Domain dataclasses/enums/ports live under catalog, execution, security and regression and must not import API schemas/FastAPI/SQLAlchemy/HTTPX. Avoid shared mutable module globals.

catalog owns immutable Definition/Revision value contracts and application services; it exposes validation ports. Pure security policies and regression canonicalization adapters implement those ports at composition. catalog never imports regression implementations; regression may consume immutable catalog values. persistence depends inward on owning contracts and implements repositories/UoW; API/worker compose public services.

Coordinator owns app.py, problems.py/problem schemas, models.py registration, migrations/env.py, fixture cleanup, migration allocation/head, generated OpenAPI/client artifacts and root/normative docs. Backend owns one allocated slice's domain/adapters/schema/router/focused tests and its allocated migration. QA owns separate acceptance files/worktree/database only. Frontend owns typed client consumption and tests against coordinator's integrated generated contract; no generated-artifact edits or M6 forms.

Dependency order: reviewed M2-00 contracts/fixtures => M2-01 supported-head readiness/fixture glue plus independent M2-02 project/ports => environments and pure test policies => immutable test cases => pinned suites => integrated acceptance. Future execution schemas are reviewed interfaces only; adapters/result transitions remain M3/M4/M5. Future import preview contract requires separate approval and is not a dependency of manual catalog authoring.

Readiness must compare the database revision against the running package's supported Alembic head policy (not hardcoded0001 or "any revision"), with real PostgreSQL tests. Existing fixture deletion only jobs/executions must be extended centrally with FK-safe catalog cleanup against task-owned disposable databases. Multiple worktrees need different databases/ports; test suffix is not permission to destroy existing records.

Minimum named contract fixtures: project create/list/notfound; environment create/rename/full-definition change; valid strict test document containing synthetic reference; rejected credential literal/context; unrelated baggage allowed; canonical reordered-object/numeric vectors; explicit unsafe replay consent; stale/missing/malformed ETag; cross-scope/invalid cursor; suite exact revision order/duplicate case/missing membership; two concurrent writes one412; transaction rollback leaves no history; catalog reads invoke no DNS/dispatch/secret resolver; canaries absent from API/logs/spans/database; future queued/evaluated/ambiguous/expired-artifact/missing-Tempo result; inventory-only and needs-configuration OpenAPI previews with no external fetch.

The current repository implements health and all 16 M2 catalog operations for
projects, versioned environments, immutable test-case revisions, and ordered
suites pinned to exact test-case revisions alongside the M1 probe execution/job
rows. M2-08's reviewed candidate synchronizes the implemented runtime catalog
schemas with the accepted planned contract without registering M3 routes.

## 12. Machine-readable handoff and implementation start

[Planned OpenAPI](../contracts/milestone-2.openapi.json) defines the catalog routes
and future components. [Synthetic fixtures](../contracts/milestone-2.fixtures.json)
provide named transport examples. `frontend/openapi.json` and its generated
TypeScript remain the active API artifacts and contain the implemented health and
M2 catalog routes only. Planned M3-and-later schemas remain planning artifacts;
do not register their routes or replace runtime artifacts with unimplemented
operations.

Run `make check-planned-contract` for the executable planning gate. Its existing
locked generator uses explicit discriminator mappings, `defaultNonNullable: false`
and schema-derived recursive type aliases through the public `postTransform` API.
Those choices preserve wire tags and optional inputs and avoid TS2502 without
handwritten client shapes or `any`. The active generator and drift checker now use
the same optional-default behavior for the implemented catalog models.

Schema validation covers structure, unions, references and bounds. Service and
policy tests must cover ETag transactions, membership, named secret placement,
credential literals, decimal canonicalization, DNS-free reads and sensitive sinks;
an OpenAPI schema alone cannot establish those invariants. Frontend handles
arbitrary precise JSON inputs as raw source text or a lossless JSON tree; it must
not round them through ordinary `JSON.parse`/`stringify`. This requires no new
dependency in this task. Future precision-dependent authoring UI is M6 scope.

Readiness is implemented as a prerequisite: the deployed backend’s `alembic.ini`
and migration graph must have exactly one head, and the database’s current heads
must match it exactly. Missing/empty/version-mismatched metadata, ambiguous or
missing migration assets and connectivity failures produce 503. The read-only
check runs no migration environment or upgrade; Tempo degradation is independent.
The supported source checkout and Docker image ship these assets together; a
standalone wheel without them fails closed and is not a supported deployment.

M2-01 catalog fixture cleanup now covers every integrated catalog foreign key.
M2-02 through M2-08 are integrated with active OpenAPI generation and typed
client consumption. Final acceptance identity and CI evidence are recorded in
the implementation ledger above. Future work follows the authorization,
ownership, isolation, and final-CI rules in the
[workflow](../development/workflow.md).
