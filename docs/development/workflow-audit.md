# Workflow audit and change report

This records the initial workflow preparation. The subsequent
[integration prerequisite review](integration-readiness.md) records the readiness
fix, resolved contract design and fresh validation; historical results below
describe the earlier candidate.

Audit date: 2026-10-09. Starting checkout: clean `main`, tracking `origin/main`,
HEAD `62635ea71566dc8e21118667a393ed944f6a0cce`. Remote is
`git@github.com-personal:amnotwallas/sentinel.git`. No commit, push, merge,
visibility change or Milestone 2 feature is authorized by this workflow task.

## Evidence inspected

- Root AGENTS, README, Git/Docker ignores; MVP, architecture and accepted ADRs
  0001–0007; roadmap and M1 implementation ledger.
- Actual backend package, configuration, API/readiness/problems/export,
  persistence/queue, worker/runtime/health paths, migrations and tests.
- Actual frontend scripts, generated contract/client, component tests and Vite
  setup; Compose/binding checker; all steps of `.github/workflows/ci.yaml`.
- Installed Codex CLI help/version/features/review help; repository configuration
  inventory and a sanitized user-configuration structure. No auth files, connector
  credentials or environment values were copied into this report.
- Independent read-only backend/M2 and frontend/CI audits. The coordinator is the
  sole repository writer; no concurrent writer shared this checkout.

Observed repository matches M1: domain catalog/security/regression are stubs;
only probe execution/jobs are persisted; health API and frontend shell exist.
Required source/tests/migration/CI/docs remain in the intended layout. Architecture
describes future entities explicitly; that is not evidence they exist already.

M1 is complete per the user's passing Actions confirmation (backend 46s,
frontend 24s, Compose 1m23s). Current roadmap/ledger status was reconciled with
the already pushed commit. Historical evidence remains intact. A run URL/log
capture is still unavailable here; this is evidence provenance, not an invented
CI failure or an acceptance blocker.

## Parallelism and collision findings

| Finding | Repository evidence | Workflow response |
| --- | --- | --- |
| Independent review can overlap implementation | Modular boundaries and separate test layers | Read-only QA plus frontend review; bounded task packets |
| Environment and test definitions logically separate | M2 immutable environment/test revisions | Parallel only after shared ports/document contracts freeze; default one backend writer |
| Migration changes currently break readiness | `api/app.py` requires revision exactly `0001` | Plan M2-01, real PostgreSQL readiness coverage before schema integration |
| Shared registration/composition files | `persistence/models.py`, `migrations/env.py`, `api/app.py`, `tests/conftest.py` | Coordinator owner; serialized integration and one migration head |
| Integration tests delete shared data | `tests/conftest.py` deletes jobs/executions | Dedicated database per task; no shared-database parallel pytest |
| Worktrees do not isolate Docker | Compose `name: sentinel` and fixed five ports | Unique project plus port overrides, initially one full-stack owner |
| Native workers collide across worktrees | `/tmp/sentinel-worker-health` in worker entry point | One native runtime; separate containers for full-stack tests |
| Regeneration overwrites candidate artifacts | `api/export.py` and `npm run api:generate` | Single generated-contract owner plus non-mutating drift checker |
| Runtime token changes contract-test behavior | M1 ledger's 401-versus-404 reproduction | Command-scoped token/host removal, clean-shell guidance |
| M2 frontend could expand scope accidentally | M2 client types; M6 authoring UI | Typed consumption/tests now; UI waits for its milestone |

## Installed Codex support

CLI 0.160.1 exposes `--worktree`, `-C`, `review --uncommitted` and `review --base`.
Feature inspection reports `multi_agent` and `worktrees` stable/enabled. This
session offers collaboration spawn/message/wait tools and four concurrent slots
including root. At the start of the audit there was no repository
`.codex/config.toml` or repository skill set. The current Codex session discovers
all four Sentinel skills from `.agents/skills/`. The user config trusts this checkout and has no custom agent-role table
or explicit concurrency setting. No global settings were changed.

Local CLI probes emitted a sandbox warning about creating PATH aliases; the
read-only help/version/feature queries still exited successfully. No daemon or
session was launched to test implementation, and no unsupported role configuration
was installed. `gh`, actionlint and dedicated secret scanners were not installed
at audit; use available Git/app capabilities and scoped review rather than inventing
commands. SSH remote naming does not establish connector-account access.

Repository skills use the documented `.agents/skills` location. Official
[skill discovery](https://learn.chatgpt.com/docs/build-skills),
[subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), and
[worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees) were checked
against installed help. Roles are task responsibilities, not assumed custom agent
configuration. The workflow works with isolated app/CLI sessions when spawn tools
are unavailable. A newly added skill may require a new session for discovery.

## Implemented workflow improvements

- [Collaboration workflow](workflow.md): four roles, file ownership, dependency
  packets/handoffs, review/integration gates, branches, resources and exact start steps.
- [M2 task plan](milestone-2-plan.md): nine dependency-aware packets, open contract
  decisions and scope-specific tests; no M2 source changes.
- [Quality reference](quality-gates.md) plus Makefile wrappers for locked setup,
  fast backend/frontend, tooling, contract and Compose configuration checks.
- `infra/check_contract.py`: generate into temporary files, remove runtime
  `SENTINEL_*` environment from subprocesses, compare both artifacts byte-for-byte,
  isolate generator configuration, and fail on drift without rewriting artifacts.
  No new package dependency.
- Four repository reference skills: feature, quality gates, security review and
  PR preparation. Baseline retrieval gaps and application tests are recorded below.
- Minimal AGENTS collaboration section and README navigation; `.worktrees/`
  excluded from Git and Docker, `.agents` excluded from Docker build contexts.
- Stale M1 current-status statements corrected with user-reported CI provenance;
  accepted architecture/ADRs and CI production behavior were preserved.

## Recommendations not applied

| Priority | Improvement | Concrete benefit / next trigger |
| --- | --- | --- |
| P0 for M2 | Readiness on supported migrated schema; catalog FK cleanup and secret-safe domain problems | Required by new schemas; planned M2-01 and shared integration, not implemented now |
| P1 | Promote the temporary controlled crash/persistence acceptance harness to tracked tests | Close the documented gap between historical acceptance and repeatable CI; preserve original-record assertions and bounded process control |
| P1 | Incremental M2 client/ETag/problem contract tests and canary privacy tests | Catch backend/frontend mismatches and persistence/log leakage as APIs land |
| P1 | Small architecture import check as domain modules grow | Catch forbidden framework/adapter imports and catalog↔regression cycles; introduce with meaningful violating fixtures |
| P2 | Native worker health path configuration if simultaneous workers become useful | Remove a demonstrated shared `/tmp` collision; containers/one runtime suffice initially |
| P2 | CI cancellation of superseded branch runs and explicit job timeouts | Reduce stale compute and hangs; retain backend/frontend/compose jobs and PostgreSQL coverage |
| P2 | Local `codex review --uncommitted` / `--base` on the exact candidate | Available additional review; do not treat generated findings as proof or install API-key-dependent Actions review now |
| P2 | A free local credential scanner and workflow lint on relevant edits | More repeatable detection; choose/install explicitly when needed, review false positives and never print matches |
| Later | Reuse validated Make targets in CI, artifacts for sanitized test/migration reports | Reduce local/CI command drift after wrappers are proven; no CI rewrite in this change |

Current CI already runs real PostgreSQL 16/full backend tests, migration up/down/
drift, frontend generated-contract drift/lint/types/tests/build, and full Compose
probe/outage checks. These are existing capabilities, not new recommendations.
The user-reported runtimes are short; path filtering, broad caches, more permanent
agents and additional orchestration infrastructure are not justified presently.
No paid service, API key requirement, remote bot, branch protection or visibility
change was introduced.

## Verification record

Fresh local checks completed on 2026-10-09:

| Exact command / procedure | Result |
| --- | --- |
| `make check-fast check-compose-config` | Passed: Ruff backend lint/35 formatted files, strict mypy 33 files, 21 backend non-integration tests (23 intentionally deselected), frontend lint/format/types, Vitest 1/1, build 29 modules, contract drift, checker lint/types and loopback Compose config |
| `make check-contract check-tooling` after generator fix | Passed on final checker: identical OpenAPI/types; Ruff and strict mypy (1 file) |
| `backend/.venv/bin/python /private/tmp/sentinel-workflow-validation/verify_postgres.py` | Passed in fresh project `sentinel-workflow-check-44040266`, `sentinel_workflow_test`: full backend 44/44 including 23 real PostgreSQL tests; task-owned resources removed |
| PostgreSQL harness: `uv run --frozen --project backend alembic -c backend/alembic.ini upgrade head`, `check`, `upgrade head --sql`, `downgrade head:base --sql`, `downgrade base`, `upgrade head`, `check`, `current` | All passed; reviewed generated up/down SQL, no drift, `0001 (head)` after round trip. Both database variables identified only the new disposable database; runtime token excluded |
| PostgreSQL harness: `uv run --frozen --project backend pytest backend/tests` | 44 passed, no SQLite or sleeps for lease semantics |
| `backend/.venv/bin/python /private/tmp/sentinel-workflow-validation/verify_contract_checker.py` | Six behavioral cases passed: matching artifacts despite invalid ambient settings; OpenAPI drift; TypeScript drift; injected multi-API config; missing artifact; missing tools. Expected exits 0/1/2; every candidate and original artifact remained unchanged |
| `backend/.venv/bin/python /private/tmp/sentinel-workflow-validation/verify_repository_workflows.py` | Four skills structurally valid, local links resolved, exact five documented port replacements/loopback verified, four manual worktrees at one base tested in a disposable local clone; actual repository branch/worktrees unchanged |
| `backend/.venv/bin/python /Users/walter/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/<name>` for each skill | Four valid manifests; application checks passed for each reference skill |
| `git diff --check` and scope comparison | No whitespace errors; index empty; backend/frontend production, product MVP/architecture/ADRs and CI unchanged |

Baseline skill application found missing ownership/handoff references, non-mutating
contract and isolated PostgreSQL procedures, a security report structure, and
uncommitted candidate evidence. Each reference was written and application-tested
before the next; all four scenarios retrieved the needed procedures. These were
read-only reference usability checks, not autonomous Milestone 2 implementation.
Future skill discovery may require a new Codex session; no new session was launched.

Independent final review found and resolved three issues: incorrect relative skill
links, generator auto-discovery able to redirect writes, and a fixed validation
project name able to reuse old volumes. The generator issue was reproduced as a
candidate-mutation failure in a disposable copy before fixing it; the same case
then passed without rewriting. Final reviewer recheck reported no remaining
findings within that scope. Backend/M2 plan review found no normative conflict.

The first local run required sandbox approval for uv's existing cache; its first
tooling format check used Ruff's root defaults rather than the backend configuration.
Make now selects the repository's Python configuration explicitly and the final
format/type checks pass. Installing repository skills likewise required permission
for the sandbox-protected `.agents` directory. These permissions did not authorize
Git publication or repository setting changes.

Validation JSON/logs and disposable-copy harnesses are under
`/private/tmp/sentinel-workflow-validation/`; they are session evidence, not newly
tracked CI tests. Scoped candidate credential-pattern review found no real
credential; it is not a comprehensive scanner or a guarantee about arbitrary
literals. Synthetic local/test credentials are intentional and labeled.

Full five-service image rebuild/startup was not repeated for this documentation/
developer-tooling change: production/Compose services and CI are unchanged.
Rendered configuration/port overrides and the documented PostgreSQL procedure
were freshly verified. Historical M1 full-stack acceptance and user-reported CI
remain separate evidence. The actual checkout stays on `main`, with these workflow
changes unstaged and no additional commit, push, merge or remote setting mutation.
