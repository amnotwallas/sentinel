# Integration prerequisite review

Review date: 2026-10-09. Branch: `main`. HEAD/base remains
`62635ea71566dc8e21118667a393ed944f6a0cce`; remote remains
`git@github.com-personal:amnotwallas/sentinel.git`. The original 17 unstaged
workflow files were reviewed; the final candidate contains 26 changed files.
Everything remains unstaged. No commit, push, merge, remote-setting change or
Milestone 2 business implementation occurred.

## Implemented and reviewed

- All four repository skills are discovered in the current Codex catalog. Their
  structure, local references and task routing were checked. CLI 0.160.1 supports
  the documented `--worktree`, `-C`, `review --uncommitted` and `review --base`;
  no custom agent configuration or `codex spawn` command is required.
- Corrected the audit's historical wording about the absence of repository
  skills. Updated start instructions and M2-00/M2-01 status to match this task.
- Added the [wire contract packet](../implementation/milestone-2.md),
  [planned OpenAPI](../contracts/milestone-2.openapi.json) and
  [synthetic cases](../contracts/milestone-2.fixtures.json). The 16 catalog
  operations use nine path templates. Future execution/result/import components
  are explicitly separate from M2 implementation and the active health contract.
- Added `make check-planned-contract`: local schema/reference checks, positive
  and negative examples, temporary TypeScript generation and example compilation.
  Existing locked Redocly/AJV tools are reused; no dependency was added.
  Corrected explicit wire discriminator mappings and optional-default generation.
  A reproduced TS2502 issue in recursive JSON types was resolved through public
  AST transforms that derive named aliases from the schema; no `any` or manually
  maintained client shapes were introduced. Unused schemas are meta-validated
  and unexpected TRACE operations are rejected.
- Replaced the `0001` readiness constant with the deployed migration graph's
  single head and Alembic's current database heads. Missing/empty metadata,
  mismatched revisions, missing/ambiguous assets and connectivity failures fail
  closed. The check reads metadata and never invokes the migration environment.
- Independent review caught repeated Alembic `prepend_sys_path` mutation during
  threaded health polling. A failing regression reproduced five added entries;
  the probe-only config now removes that option. Repeated probes leave import
  paths unchanged. No accepted ADR, schema migration, lock or CI workflow changed.

The API continues using Pydantic v2. No framework-specific catalog domain models,
business routes, importer, HTTP adapter, frontend authoring UI or orchestration
service was introduced. A checkout and Docker image ship `alembic.ini` and
migrations together; an assetless standalone wheel is unsupported and fails closed.

## Contracts and ownership

The contract packet fixes creation/update/detail/list shapes, immutable revision
documents, reference placement, suite pins, canonical policy serialization,
ETag preconditions, cursor ordering/bounds, errors and synthetic examples.
Environment declarations contain exact tagged secret names; they neither grant
access nor resolve values. Known credential literals and Sentinel-owned trace
context must be rejected by later service/boundary tests.

| Owner | Exclusive responsibility |
| --- | --- |
| Coordinator | Contract packet/planned schema, shared API/problem wiring, model/fixture registration, linear migration allocation, active generated artifacts and integration evidence |
| Backend | One task's named catalog/domain/service/adapters/routes/schemas/tests and allocated migration; proposes shared wiring |
| Frontend | Named typed client/consumption tests against integrated generated types; planned examples can be reviewed beforehand; authoring UI remains M6 |
| QA/security | Read-only review or separately allocated acceptance tests in its own worktree/database; findings go to the production owner |

Domains use independent dataclasses/enums/ports. Pydantic belongs at API/config
boundaries; persistence adapters implement domain ports. Catalog exposes
validation interfaces rather than importing regression implementations.
No two writers share a file or database. Shared wiring, migration ordering,
contract regeneration and final integration remain sequential.

## Actual quality results

All final validation commands exited 0. The intentional TDD failures below are
recorded separately; they are not unresolved gate failures.

| Gate | Command/evidence | Result |
| --- | --- | --- |
| Backend lint/format/types | `make check-backend` through `make check-fast` | Ruff passed; 38 files formatted; mypy passed on 36 files |
| Non-PostgreSQL tests | Wrapper's `pytest backend/tests -m 'not integration'` | 22 passed, 33 deselected |
| Focused readiness | `uv run --frozen --project backend pytest backend/tests/integration/test_readiness.py backend/tests/contract/test_database_readiness.py -q` | 11 passed |
| Full backend/PostgreSQL | `uv run --frozen --project backend pytest backend/tests` | 55 passed, including 33 integration tests; no warnings |
| Frontend | `make check-frontend` | ESLint, Prettier, strict TypeScript, Vitest 1/1 and Vite build passed |
| Active contract | `make check-contract` | OpenAPI and TypeScript byte-for-byte match; artifacts unchanged |
| Contract checker behavior | `python3 /private/tmp/sentinel-workflow-validation/verify_contract_checker.py` | Six cases pass: match, spec/type drift, multi-API config, missing artifact/tools; expected 0/1/2 statuses and no artifact mutation |
| Planned contract | `make check-planned-contract` | 16 operations, 121 schemas and 74 cases (36 positive/38 negative); generated positive examples compile without `any`; runtime artifacts unchanged |
| Planned checker behavior | `python3 /private/tmp/sentinel-planned-mutations.py` | Matching contract exits 0; invalid unused schema and unexpected TRACE exit 1; runtime artifact hashes unchanged in all three cases |
| Tooling | `make check-tooling` | Python Ruff/mypy, Node syntax and planned checker/JSON formatting pass |
| Compose config | `make check-compose-config` and actual task override | All five published ports are loopback-only; override replaces fixed bindings |
| Skills | `backend/.venv/bin/python /Users/walter/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/NAME` for each of four names | Four valid; current catalog discovery and independent routing/reference review confirmed |
| Worktrees/docs/security scope | `backend/.venv/bin/python /private/tmp/sentinel-prereq-repository-check.py` | Local links, four worktrees at one base in disposable clone, empty index, protected scope and scoped credential patterns checked |
| Full Docker | Explicit migration, rebuilt five-service startup, worker probe, API readiness, frontend health proxy and Tempo outage | All passed; task-owned resources removed |

PostgreSQL/Docker evidence was collected in a fresh project
`sentinel-prereq-e27667ec`, database `sentinel_prereq_test`, with ports
56681 (PostgreSQL), 56682 (API), 56683 (frontend), 56684 (Tempo HTTP),
56685 (OTLP). No existing development stack or volume was reused or stopped.
The coordinator-owned temporary runner was
`python3 /private/tmp/sentinel-prereq-validate.py`; exact commands, exits and logs
are retained under `/private/tmp/sentinel-prereq-validation/`.

After making the readiness-test future graphs derive their parent from the
database's current revision rather than `0001`,
`python3 /private/tmp/sentinel-prereq-final-postgres.py` reran the 11 focused and
55 full backend tests plus SQL/up/down/drift checks in another fresh project,
`sentinel-prereq-pg-adb83af4`. All passed and its resources were removed. Evidence
is under `/private/tmp/sentinel-prereq-final-postgres/`. Runtime files did not
change after the full Docker verification, so the Docker result remains applicable.

With the isolated database URL injected, migration commands were:

```sh
uv run --frozen --project backend alembic -c backend/alembic.ini upgrade head
uv run --frozen --project backend alembic -c backend/alembic.ini check
uv run --frozen --project backend alembic -c backend/alembic.ini upgrade head --sql
uv run --frozen --project backend alembic -c backend/alembic.ini downgrade head:base --sql
uv run --frozen --project backend alembic -c backend/alembic.ini downgrade base
uv run --frozen --project backend alembic -c backend/alembic.ini upgrade head
uv run --frozen --project backend alembic -c backend/alembic.ini check
uv run --frozen --project backend alembic -c backend/alembic.ini current
```

Upgrade/down SQL was inspected: deterministic execution/job table constraints
and indexes, then jobs/executions dropped only in the new disposable database.
Both drift checks reported no new operations; final revision was `0001 (head)`.
No catalog migration was created. The focused fixtures supply temporary future
graphs instead. They exercise empty-schema startup, missing/empty/unknown metadata,
pending/current future heads, multi-head/missing assets, a migration-environment
trap, refused real connections, safe response/log output and repeated probes.

Docker used the same project's rendered override and `--env-file /dev/null`:
`run --build --rm api alembic upgrade head`,
`up -d --build --wait --wait-timeout 180`,
`exec -T api python -m sentinel.worker.smoke`, frontend/API HTTP checks,
`stop tempo`, then `down --volumes` for that task-owned project only.
All five services were healthy; the durable worker probe completed. Tempo outage
returned HTTP 200 with `status=ready`, `postgres=available`, `tempo=unavailable`.

TDD evidence: two tests failed against the original `0001` probe (pending accepted,
matching future head rejected); the repeated-probe test then failed against the
first adapter revision. All pass after correction. Initial sandbox access to
Docker/uv was denied; reruns used approved access. There are no remaining local
test failures. No remote CI run exists for this unpublished candidate; M1 CI
remains the user's previously confirmed passing run, not a new inspected run.

The planned-contract gate initially failed on discriminator/default generation
and recursive TypeScript types; those were confirmed generator compatibility
defects and are now resolved. The repository validation harness initially used
system Python, which lacked PyYAML; rerunning it with the existing backend virtual
environment passed without installing a dependency.

## Remaining decisions and unapplied work

There is no local readiness or workflow validation blocker to M2-02. Feature
implementation still requires the user's authorization and a common worktree
base containing these reviewed prerequisites. New worktrees from today's HEAD
alone omit all uncommitted files.

- OpenAPI imports are outside accepted MVP/M2 scope. The documented future
  preview interface accepts local JSON only, forbids remote references/fetching,
  returns reviewable proposals and persists nothing. Product/roadmap and any
  material ADR approval precede implementation; imports do not block manual
  catalog authoring.
- Before M3, resolve recorded transport-failure checkpoint semantics and any
  operator policy allowing explicit TLS opt-out. Future result schemas do not
  silently add state transitions.
- Before M4, resolve first-required-baseline bootstrap: absent required baseline
  yields `baseline_required`, while ADR 0004 excludes that verdict from promotion.
  Also decide immutable baseline selection time and normalizer-error verdict
  mapping. No workaround or accepted-history rewrite was applied.
- Catalog FK cleanup is applied centrally when the actual tables land, with
  isolated databases. Planned structural examples do not establish runtime
  Pydantic, transactional, precision, byte-limit or security-sink conformance.
- CI automation for the new planned-contract/tooling/skill checks remains a
  recommendation. Existing CI was preserved; no paid review service or extra
  orchestration infrastructure was introduced. Dedicated credential scanners
  are absent; scoped pattern/manual review is not a comprehensive scanner.
- When optional/recursive planned models enter the active API, apply the verified
  generation options/AST transform to the active generator and drift checker in
  that coordinator-owned slice. Today's health generator is unchanged.

## Exact start sequence after authorization

1. Authorize the M2-02 project slice. Make this reviewed candidate available as
   an explicitly authorized prerequisite commit, or transfer its exact reviewed
   files/diff with hashes to every new worktree. Commit authorization and feature
   authorization are separate; neither is inferred from this report.
2. Run the commands in [starting parallel work](workflow.md#starting-parallel-work):
   record the actual base SHA, check ignores/existing branches, then create
   `integration/m2-catalog`, `feat/m2-projects`, `test/m2-contract-consumption`
   and `test/m2-catalog-acceptance` at that same base. These worktrees have not
   been created in the real repository by this task.
3. Run `codex -C /absolute/worktree` for each needed writer session, or explicitly
   direct collaboration agents to that absolute worktree. Run `make setup` and
   relevant gates there. Reserve distinct `_test` databases/ports; initially one
   coordinator owns the full Compose stack. Do not combine an existing worktree
   with another `--worktree` flag or assume spawned agents are isolated.
4. Backend implements M2-02 with exclusive project/service/adapter/test files.
   Coordinator allocates the next migration (`0002`, parent `0001`, only after
   confirming no other allocation), reviews it and applies shared registration/
   fixture/wiring changes. QA independently prepares named acceptance/security
   cases; frontend reviews the planned contract and prepares fixture expectations.
5. Coordinator integrates the project slice and regenerates active Pydantic
   OpenAPI/client types once. Frontend then implements M2-04 typed consumption
   while backend starts M2-03 environments and QA reviews the integrated project
   candidate. Continue the plan's dependency order with the combined gates.

The first useful parallel implementation is backend M2-02 plus independent QA
case preparation. Frontend becomes an implementation writer after the generated
project handoff. This keeps the critical path short without inventing parallel
work that still depends on unfinished contracts.

## Final changed files

Seven modified tracked files:

```text
.dockerignore
.gitignore
AGENTS.md
README.md
backend/src/sentinel/api/app.py
docs/ROADMAP.md
docs/implementation/milestone-1.md
```

Nineteen new files, including the previously prepared workflow files:

```text
.agents/skills/sentinel-feature/SKILL.md
.agents/skills/sentinel-pr-prepare/SKILL.md
.agents/skills/sentinel-quality-gate/SKILL.md
.agents/skills/sentinel-security-review/SKILL.md
.github/PULL_REQUEST_TEMPLATE.md
Makefile
backend/src/sentinel/persistence/readiness.py
backend/tests/contract/test_database_readiness.py
backend/tests/integration/test_readiness.py
docs/contracts/milestone-2.fixtures.json
docs/contracts/milestone-2.openapi.json
docs/development/integration-readiness.md
docs/development/milestone-2-plan.md
docs/development/quality-gates.md
docs/development/workflow-audit.md
docs/development/workflow.md
docs/implementation/milestone-2.md
infra/check_contract.py
infra/check_planned_contracts.mjs
```
