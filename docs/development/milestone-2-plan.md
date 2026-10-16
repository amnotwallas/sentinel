# Milestone 2 task plan

Milestone 2 implementation is in progress. The schema-readiness prerequisite,
project API, versioned environment API, typed-client acceptance coverage, and test
definition policy are integrated. Scope and exit criteria come from
[ROADMAP.md](../ROADMAP.md#milestone-2-versioned-catalog-and-definition-api),
with endpoint inventory in [MVP.md](../MVP.md#api-acceptance-contract). The accepted
[architecture](../architecture/README.md) and ADRs remain unchanged. Milestone 1
is accepted per the user's CI confirmation. M2-03 is integrated on `main` as
`fc9c3aa46838fa2b6f754f8973990d5480b8bede`; the user confirmed Actions run #3
completed successfully in 1 minute 18 seconds. The run URL and individual backend
and Compose job details are not recorded yet.

## Decisions before compatibility surfaces

M2-00's wire details and synthetic fixtures are recorded in the
[implementation packet](../implementation/milestone-2.md) and its planned schema.
The following decisions are resolved there; agents must use that baseline and
coordinate any change before generating runtime compatibility surfaces:

- Create/read/list/update payloads, cursor ordering/bounds/invalid-cursor errors,
  and what mutable state each strong ETag covers. Define missing, malformed,
  weak, wildcard and multiple `If-Match` handling; stale values already require
  `412`/`revision_conflict`. Do not add a project PATCH endpoint absent from the MVP.
- Environment metadata-only versus revision-producing edits, secret-reference
  representation, and atomic activation/change-event behavior.
- Suite input pinning, empty/duplicate-case rules and ordinal convention. Preserve
  exact immutable revision IDs, membership ownership and order.
- Versioned request/assertion/comparison/redaction/target-policy document schemas;
  supported wire forms for limits, TLS, redirects and replay acknowledgement.
  ADR 0007 requires explicit acknowledgement for unsafe replay, beyond the sample
  boolean. M2 stores/validates policy; it performs no DNS resolution or target I/O.
- Canonical numeric/Unicode serialization, omitted/default treatment, normalizer
  versions and `round_decimal` mode/scale. Sorting object keys and preserving
  array order are already required. Fingerprints exclude UI metadata.
- Safe ChangeEvent kinds/summaries and versioned redaction persistence. Test
  revision history has an endpoint; environment/suite/global history endpoints
  are not in the normative inventory and must not be silently added.

Complete unspecified details with documented review. A material semantic change
requires an ADR first. Catalog validation ports are implemented by pure security
and regression policies at composition time; avoid catalog importing regression
implementations when regression already depends on immutable catalog value types.

## Ownership rules for all slices

The backend agent owns slice-specific domain/services, persistence adapters,
routers/schemas and focused tests. Suggested new paths below are proposals, not
existing code. Finalize them in the task packet; keep files focused, without a
premature generic CRUD framework. Domain code remains framework-independent.

Coordinator owns `api/app.py`, shared `api/problems.py`/problem schemas,
`persistence/models.py` registration, `migrations/env.py`, `tests/conftest.py`,
migration revision allocation, generated artifacts and root documentation.
Backend receives exclusive ownership of each allocated migration file and writes
it with the corresponding vertical slice; coordinator reviews/integrates the
chain and shared wiring. QA writes only allocated acceptance files; frontend
writes client-consumption tests/source, not generated artifacts.

## Task packets

### M2-00 — Freeze definition contracts

- **Objective:** Resolve the decisions above and turn every M2 exit criterion
  into a named acceptance case before API/database compatibility surfaces exist.
- **Owned files:** Coordinator's `docs/implementation/milestone-2.md` contract
  packet and `docs/contracts/milestone-2.*` planned schema/fixtures; reference
  normative docs without copying them. Amend normative
  documents/ADRs only if the agreed decision requires it.
- **Dependencies / agent:** None; coordinator, with backend/frontend/QA read-only input.
- **Acceptance / tests:** Reviewed payload examples, port/error/ETag contracts,
  document versions, mapping plan, reserved migration IDs and ownership matrix;
  acceptance case inventory links to each roadmap requirement. Validate examples
  against actual schemas as each later slice lands.
- **Status:** Contract design completed as an integration prerequisite; runtime
  Pydantic schemas and API contract tests land with their individual slices.
- **Parallel:** Read-only reviews can run together. Feature work waits for authorization.

### M2-01 — Keep upgraded schemas ready and tests isolated

- **Objective:** Remove the migration integration trap before catalog schemas land.
- **Owned files:** Coordinator's `api/app.py`, `persistence/readiness.py`,
  `tests/integration/test_readiness.py`, `tests/contract/test_database_readiness.py`,
  migration/model registration glue and `tests/conftest.py` as needed.
- **Dependencies / agent:** M2-00; coordinator as integration writer.
- **Acceptance:** Document the supported schema-version readiness policy; current
  supported head is ready, missing/unsupported schema is unavailable, and Tempo
  outage still does not fail PostgreSQL-backed readiness. Fixture cleanup supports
  future catalog foreign keys without deleting another worktree's data.
- **Tests:** Real PostgreSQL readiness against migrated schema, missing/version
  mismatch cases, existing health/queue/worker suite and Compose startup.
- **Status:** Supported-head readiness is implemented and verified. Catalog
  FK-safe fixture cleanup remains pending until M2-02 introduces those tables;
  the coordinator applies that change with the actual schema, not in advance.
- **Parallel:** May overlap M2-02's exclusively owned files. Shared wiring and
  database integration wait for this prerequisite. No generic 'any revision is OK' shortcut.

### M2-02 — Project API and durable catalog transaction foundation

- **Objective:** Deliver create/list/read projects through API with durable identity
  and safe append-only change records; establish transaction/port contracts once.
- **Owned files:** Backend's proposed `catalog/projects.py`, `catalog/ports.py`,
  `catalog/changes.py`, `persistence/catalog/projects.py`,
  `persistence/catalog/changes.py`, `api/catalog/projects.py`, slice-specific
  schemas, allocated project/change migration, and `test_projects.py` files in
  unit/integration/contract layers. Coordinator applies shared wiring.
- **Dependencies / agent:** M2-00; integration requires M2-01. Backend.
- **Acceptance:** MVP project POST/GET/list endpoints, UUID/UTC, unique undeleted
  project names, agreed cursor envelope and safe problems. Transaction rollback
  leaves no partial resource/change event; services own decisions, API invokes them.
- **Tests:** Service unit tests; PostgreSQL persistence/constraints/rollback;
  API create/read/list/not-found/validation/pagination/auth and safe problem schemas;
  migration upgrade/downgrade/drift and generated contract gate.
- **Status:** Implemented, verified, and integrated on `main`.
- **Parallel:** Frontend can examine the existing client; QA drafts cases from
  M2-00. New typed project consumption waits for the generated handoff.

### M2-03 — Versioned environment API

- **Objective:** Create/read/list/update environments with immutable reproducible
  revisions, safe reference-only definitions and concurrency-protected activation.
- **Owned files:** Backend's `catalog/environments.py`,
  `persistence/catalog/environments.py`, `api/catalog/environments.py`,
  `security/definition_policy.py` environment policy section (exclusive ownership),
  allocated environment migration and `test_environments.py` at all three layers.
- **Dependencies / agent:** M2-01, M2-02 and environment contract from M2-00. Backend.
- **Acceptance:** Revision 1 on creation; agreed PATCH produces history as specified;
  old revisions remain byte-equivalent, versions increase, pointer and ChangeEvent
  commit atomically. Stale `If-Match` returns 412 without a write. Validate base URL,
  variable/reference/target-policy documents statically; never resolve references.
- **Tests:** Immutable revisions, malformed/static policy, two independent PostgreSQL
  update transactions, rollback, scoped ownership, canary errors/logs/persistence,
  exact MVP endpoint contracts, migrations and generated types.
- **Status:** Integrated on `main` as
  `fc9c3aa46838fa2b6f754f8973990d5480b8bede`. GitHub Actions run #3 is
  user-confirmed successful in 1 minute 18 seconds, with 2 passing frontend Vitest
  files and 4 passing tests; the run URL and individual backend and Compose job
  details remain to be captured.
- **Parallel:** Frontend M2-04 and QA review of the project slice can run concurrently.
  Pure test-document validation could be split with a new explicit writer, but the
  default model keeps one backend writer and avoids overlapping security modules.

### M2-04 — Typed client consumption for each stable API slice

- **Objective:** Prove generated types support M2 endpoints, pagination, reference
  documents, ETag/If-Match and stable problems without handwritten schema copies.
- **Owned files:** Frontend's `src/shared/api/client.ts`, proposed
  `tests/api/catalog-client.test.ts` and compile-checked synthetic request examples.
  Coordinator owns `openapi.json` and `src/shared/api/generated/schema.ts`.
- **Dependencies / agent:** First increment after M2-02's integrated generated
  contract; extend after M2-03, M2-06 and M2-07. Frontend.
- **Acceptance:** Typed endpoint calls use the generated contract, preserve headers
  and handle documented errors. No definition forms, query-library expansion or
  backend state machines in the frontend. UI remains M6 scope.
- **Tests:** Vitest with injected/mock fetch exercising successful and stale-update
  responses; strict TypeScript compile rejects incompatible shapes; drift, lint,
  format and build. Use synthetic references without environment lookup.
- **Parallel:** Yes, against a frozen generated contract while backend builds the
  next slice. Suspend edits during shared contract regeneration/handoff.
- **Status:** Integrated on `main` as
  `7783038965a007c9b80234565be467faaca49afb`, with local runtime acceptance
  coverage for typed project/environment reads, pagination, ETag/Location access,
  If-Match transmission, stale-update problem responses, frontend quality gates,
  and generated-contract drift. Remote CI verification remains pending.

### M2-05 — Validate a test definition and return safe boundary errors

- **Objective:** Deliver strict test-document validation reusable by the creation
  service, including policy fingerprinting and safe transport failures.
- **Owned files:** Backend's `catalog/definitions.py` value types/validator ports,
  `security/definition_policy.py` test section (ownership transferred after M2-03),
  `regression/policy.py` validation/canonicalization only, test request schemas and
  `test_definition_policy.py` unit/contract files. Coordinator maps shared problems.
- **Dependencies / agent:** M2-00 contracts and M2-02 service ports. Backend;
  scheduled after M2-03 with the default single backend writer.
- **Acceptance:** Canonical request/assertion/comparison/redaction/target documents;
  known credential-header literals rejected case-insensitively; tagged references
  allowed only in header/JSON leaves with accepted syntax; traceparent/tracestate
  and Sentinel-owned baggage rejected. Valid unrelated baggage remains allowed.
  Canonical SHA-256 is stable across object order/processes and preserves array
  order. No evaluation engine, DNS or outbound HTTP is introduced.
- **Tests:** Valid/invalid synthetic vectors for all document sections, normalizer
  parameters, limits and pointers; fingerprint determinism/change sensitivity;
  canaries absent from validation responses/logs/spans. This is a dependency-sized
  validation slice; persisted user workflow follows immediately in M2-06.
- **Parallel:** QA M2-08 can prepare adversarial cases from agreed schemas; no
  second writer modifies the same policy module. Optional pure-policy split needs
  separate files, explicit ports and a slot freed by another role.
- **Status:** Integrated on `main` as
  `46083d7e84bbb224e4f8de7f0f41c9844e86fc31`, with strict canonical validation,
  separated security/regression ownership, stable fixture fingerprints,
  security-focused unit coverage, and 39 passing PostgreSQL integration tests.
  Acceptance remains open until backend, frontend, and Compose remote CI pass on
  the resulting `main` SHA. Persistence use by M2-06 remains future work.

### M2-06 — Immutable test-case API and revision history

- **Objective:** Create/list/read/update tests and list immutable revision history.
- **Owned files:** Backend's `catalog/test_cases.py`,
  `persistence/catalog/test_cases.py`, `api/catalog/test_cases.py`, allocated
  test-case migration and `test_test_cases.py` files at each relevant layer.
- **Dependencies / agent:** M2-01, M2-02, M2-05. Backend.
- **Acceptance:** PUT creates/activates a new monotonic immutable revision with
  persisted validated documents, policy fingerprint and safe change evidence;
  previous revisions stay intact. ETag concurrency is enforced in the transaction.
  Reads return references without touching `SENTINEL_SECRET_*`. Revisions contain
  everything a future execution needs; no execution endpoint or target I/O yet.
- **Tests:** Unit service invariants; real PostgreSQL concurrent same-ETag writes
  (one success/one 412), rollback and revision uniqueness; all MVP test endpoints,
  history/pagination, canaries in database/logs/errors; migration round trip and
  contract generation. Request-only changes must not alter policy fingerprints.
- **Parallel:** Frontend extends environment client tests; QA reviews M2-03/05.
- **Status:** Integrated on `main` as
  `3c50c2bb05f68a15c83df4312f7b1877797ce426`. Local backend, frontend,
  PostgreSQL, migration, contract, and Compose gates passed; the candidate
  included 160 non-integration backend tests, 47 PostgreSQL integration tests,
  and 8 frontend tests. The user confirmed GitHub Actions workflow #5 reported
  success for this main SHA. M2-06 acceptance is recorded as complete; no
  execution or target I/O was added.

### M2-07 — Ordered suites pinned to exact test revisions

- **Objective:** Create/list/read/update ordered immutable suites through the API.
- **Owned files:** Backend's `catalog/suites.py`, `persistence/catalog/suites.py`,
  `api/catalog/suites.py`, allocated suite/item migration, `test_suites.py` files.
- **Dependencies / agent:** M2-06 integrated revision repository contract. Backend.
- **Acceptance:** Suite revision items persist exact test-case revision IDs and
  agreed ordinals; membership belongs to the same project. Later test edits cannot
  change historical suite contents. Versions, activation and safe change evidence
  commit together; stale updates cannot overwrite the pointer.
- **Tests:** Ordered pinning, later test update, cross-project/missing revision,
  agreed empty/duplicate rules, rollback and simultaneous updates on PostgreSQL;
  exact MVP suite endpoints; migration up/down/drift and generated contract.
- **Parallel:** Frontend extends test-case client tests; QA reviews M2-06.

### M2-08 — Independent acceptance/security review and milestone integration

- **Objective:** Verify the complete API definition journey and all M2 exit criteria.
- **Owned files:** QA's proposed `tests/integration/test_catalog_acceptance.py` and
  `tests/contract/test_catalog_privacy.py`; coordinator's implementation ledger,
  integrated wiring/generated artifacts. Findings go to the owning implementer;
  reviewer does not silently fix production code.
- **Dependencies / agent:** Case design after M2-00; execution incrementally as
  slices land; final acceptance after M2-03/04/06/07. QA plus coordinator integration.
- **Acceptance:** All nine catalog entities exist; API authoring is durable across
  restart, history is append-only, pins require no mutable documents, stale updates
  are safe, and no resolved secrets or target requests occur. M1 probes/readiness
  continue to work on the upgraded schema.
- **Tests:** Complete synthetic project→environment→test→suite journey, original
  revision/history retention, two-connection concurrency without sleeps, rollback,
  canary absence across persistence/logs/spans/problems, migration head/SQL/round
  trip, full backend/frontend/contract/Compose gates and all three CI jobs after
  authorized push. Network spies target dispatch/DNS/secret resolution; existing
  health probes may still contact PostgreSQL/Tempo and are not target execution.
- **Parallel:** Independent review/test files can run beside implementation using
  a different test database. Final combined acceptance and integration are sequential.

## Dependency order and critical path

```text
M2-00 → [M2-01 || early M2-02 work] → integrated M2-02
backend:  M2-03 → M2-05 → M2-06 → M2-07
frontend: M2-04 increments after each integrated generated contract
QA:       M2-08 case design/review increments → final acceptance
```

The default critical path is contract agreement → project transaction foundation
→ test definition/revision persistence → suites → integrated acceptance. Environment
and test-case workflows are logically independent after the project/ports freeze;
the default single backend writer serializes them to avoid coordination overhead.
If measured backend delay dominates, temporarily assign an available implementer
the pure-policy files and tests, freeze its interface, and keep schema integration
serial. Do not add agents to shorten work that still shares files or a database.

Use the [workflow's start steps](workflow.md#starting-parallel-work) and
[quality gates](quality-gates.md). Start with one reviewed vertical slice; do not
implement every catalog table in a single foundation PR. Re-run only affected
focused gates during iteration, then the combined required gates at integration.
Update task ownership when a slice finishes; do not keep idle sessions running.
