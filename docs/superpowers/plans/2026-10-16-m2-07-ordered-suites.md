# M2-07 Ordered Suites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the accepted M2-07 ordered suite API with immutable revisions that pin exact test-case revision IDs and preserve project ownership, ordering, concurrency, and transaction guarantees.

**Architecture:** Extend the existing catalog ports and PostgreSQL unit of work with suite identity, immutable suite revisions, and revision items. The domain service validates project membership and creates the revision, active pointer, metadata version, and ChangeEvent in one transaction. FastAPI remains a transport adapter; generated OpenAPI/TypeScript artifacts are coordinator-owned compatibility surfaces.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, PostgreSQL JSONB/foreign keys, Alembic, pytest, TypeScript/OpenAPI generation, Vitest.

**Spec:** `docs/development/milestone-2-plan.md` M2-07 and `docs/implementation/milestone-2.md` §§2, 3, 4, 5, 11.

## Global Constraints

- Suite writes accept `name` and `test_case_revision_ids`, with 1–100 ordered unique revision IDs.
- Input order becomes contiguous ordinals `0..n-1`; one test case may appear only once.
- Every pinned revision must exist and belong to the suite project; missing or cross-project membership returns `404 resource_not_found`.
- Suite revisions are immutable; a valid update always creates version `n+1`, updates the active pointer/state version, and records safe ChangeEvent evidence atomically.
- PUT requires exactly one strong quoted suite ETag; missing is `428`, malformed/weak/wildcard/multiple is `422`, stale/other-resource valid tokens are `412`.
- No execution, target I/O, secret resolution, import, or M2-08 acceptance functionality is added.
- Domain code remains independent of FastAPI and SQLAlchemy; API invokes the suite application service.

## Review Focus

- A later test-case revision must not alter a stored suite revision; integration tests inspect persisted item revision IDs and versions after the test changes.
- Concurrent same-ETag suite updates must yield exactly one success and one `412`, with one active pointer and no losing history/event.
- A revision ID from another project or a nonexistent revision must not be distinguishable through a different error shape or persist partial suite state.
- Duplicate test-case membership across different revision IDs and empty input must be rejected before persistence.
- Failed ChangeEvent persistence must roll back the suite identity, revision items, active pointer, and event together.

### Task 1: Define failing suite domain and persistence acceptance tests

**Files:**
- Create: `backend/tests/unit/test_suites.py`
- Create: `backend/tests/integration/test_suites.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes M2-06 `TestCaseRepository` and `CatalogUnitOfWork` contracts.
- Produces named tests for service invariants, PostgreSQL constraints, rollback, project ownership, and concurrency.

- [ ] **Step 1: Write unit tests** for creation ordering, duplicate/empty rejection, missing revision lookup, immutable update versions, and stale state-version rejection.
- [ ] **Step 2: Run the focused unit suite** and confirm it fails because suite domain/service types do not exist.
- [ ] **Step 3: Write PostgreSQL integration tests** for exact revision pinning, later test edits, cross-project/missing revision rejection, rollback, two-connection stale updates, and schema-level ownership constraints.
- [ ] **Step 4: Run the focused integration tests** against a dedicated M2-07 PostgreSQL database and confirm expected collection/import failures until implementation exists.

### Task 2: Implement framework-independent suite domain and ports

**Files:**
- Create: `backend/src/sentinel/catalog/suites.py`
- Modify: `backend/src/sentinel/catalog/ports.py`

**Interfaces:**
- Produces `SuiteRevisionItem`, `SuiteRevision`, `Suite`, `SuitePage`, `SuiteService`, and suite-specific errors.
- Produces repository protocols for suite identity/revision persistence and pinned revision lookup by suite project.

- [ ] **Step 1: Implement the smallest domain model required by the failing unit tests.**
- [ ] **Step 2: Implement `SuiteService.create`, `get`, `list`, and `update` with injected IDs/clock, project checks, exact input-order ordinals, unique-case validation, monotonic versions, and atomic UoW calls.
- [ ] **Step 3: Run unit tests and the existing catalog unit suite.**

### Task 3: Implement PostgreSQL persistence and migration

**Files:**
- Create: `backend/src/sentinel/persistence/catalog/suites.py`
- Create: `backend/migrations/versions/0005_catalog_suites.py`
- Modify: `backend/src/sentinel/persistence/models.py`
- Modify: `backend/src/sentinel/persistence/catalog/unit_of_work.py`

**Interfaces:**
- Consumes domain suite types and M2-06 test-case tables.
- Produces relational suite identity, immutable revision, ordered item storage, and a repository implementation used by `SuiteService`.

- [ ] **Step 1: Add the migration and ORM model constraints** for project ownership, immutable revision identity/version uniqueness, contiguous ordinal bounds, item uniqueness, and exact revision-to-test-case ownership.
- [ ] **Step 2: Implement repository conversion and pinned revision lookup without loading mutable test-case active pointers.**
- [ ] **Step 3: Register suites in `PostgresCatalogUnitOfWork` and extend fixture cleanup with FK-safe suite deletion order.**
- [ ] **Step 4: Run migration SQL/up/down/drift checks and the focused PostgreSQL integration tests.**

### Task 4: Implement the suite HTTP adapter and runtime wiring

**Files:**
- Create: `backend/src/sentinel/api/catalog/suites.py`
- Modify: `backend/src/sentinel/api/app.py`

**Interfaces:**
- Consumes `SuiteService` and existing pagination, problem, exact-JSON, and ETag patterns.
- Produces `GET/POST /api/v1/projects/{project_id}/suites`, `GET/PUT /api/v1/suites/{suite_id}`, stable problems, Location/ETag headers, and canonical suite responses.

- [ ] **Step 1: Write contract tests for create/list/get/update, ordering, stale/malformed ETags, duplicate/empty input, missing/cross-project revisions, and sanitized errors.**
- [ ] **Step 2: Run the focused contract suite and confirm it fails for missing routes/wiring.**
- [ ] **Step 3: Implement strict transport schemas and route mapping without duplicating domain decisions or reflecting submitted IDs in problem bodies.**
- [ ] **Step 4: Run focused contract tests and the existing API contract suite.**

### Task 5: Synchronize generated contracts and typed client acceptance

**Files:**
- Modify: `frontend/openapi.json`
- Modify: `frontend/src/shared/api/generated/schema.ts`
- Modify: `frontend/tests/api/catalog-client.test.ts`
- Modify: `infra/check_contract.py` if generator coverage requires it

**Interfaces:**
- Consumes runtime FastAPI OpenAPI for the four suite routes.
- Produces generated suite request/response types and typed ETag/Location contract coverage; no UI authoring.

- [ ] **Step 1: Add typed client acceptance cases using synthetic suite payloads and stale-update problems.**
- [ ] **Step 2: Generate coordinator-owned OpenAPI/TypeScript artifacts from the integrated runtime.**
- [ ] **Step 3: Run contract drift, strict TypeScript, and frontend tests/build.**

### Task 6: Documentation and final verification

**Files:**
- Modify: `docs/development/milestone-2-plan.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/implementation/milestone-2.md`

- [ ] **Step 1: Record M2-06 acceptance evidence and M2-07 implementation status without changing accepted wire contracts.**
- [ ] **Step 2: Run backend, PostgreSQL, migration, contract, frontend, tooling, Compose, and security/privacy checks required by the quality-gate reference.**
- [ ] **Step 3: Review candidate identity, changed paths, secret-pattern scan, migration SQL, concurrency evidence, and remaining risks.**

## Self-Review

The plan covers the four runtime suite routes, immutable persistence, exact revision pinning, ownership, ordering, duplicate/empty rules, ETags, transactions, generated contracts, docs, and required PostgreSQL/migration verification. It does not add execution or M2-08 acceptance behavior. The only shared writers are the coordinator-owned model/UoW/app/migration/generated/docs files; suite domain, persistence, router, and focused tests remain slice-owned.
