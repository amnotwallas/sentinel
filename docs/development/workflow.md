# Sentinel development workflow

This is a developer collaboration guide, not a change to the product architecture.
[AGENTS.md](../../AGENTS.md), the [MVP](../MVP.md), [architecture](../architecture/README.md),
accepted ADRs, and [roadmap](../ROADMAP.md) remain authoritative. The
[audit](workflow-audit.md) records evidence and unapplied recommendations;
the [Milestone 4 planning handoff](milestone-4-handoff.md) records the accepted
M4-00 inputs and resolutions, while the [M4 task plan](milestone-4-plan.md)
records the frozen slice boundaries and sequence. Milestone 3 and earlier plans
remain historical ledgers.

## Roles and ownership

Use the smallest useful team: coordinator plus one writer for a sequential slice;
add frontend and QA when they have independent work. Four roles are a ceiling,
not four permanently running agents. Stop spawning when the next task depends on
the current writer. Agents inherit the available model; no model matrix is needed.

| Role | Responsibility | Write ownership |
| --- | --- | --- |
| Coordinator/integration | Scope, dependency ordering, task packets, resource allocation, contract decisions, integration and evidence | Shared wiring, model registration, migration chain, OpenAPI/generated types, root policy/docs, CI/infra unless explicitly assigned |
| Backend implementer | Domain/application behavior, adapters, transport schemas/routes and focused tests | The slice's named backend files; proposes migrations and wiring to coordinator |
| Frontend implementer | Typed API consumption, component behavior and accessibility when the milestone permits UI | Named frontend source/tests; consumes the coordinator's generated contract |
| QA/security reviewer | Independent invariant, concurrency, privacy and regression review; reproducible findings | Read-only by default. When assigned acceptance tests, only separately named test files in its own worktree |

One writer owns each file at a time. Shared files include `api/app.py`,
`api/problems.py`, `persistence/models.py`, `migrations/env.py`,
`tests/conftest.py`, dependency locks, the two generated API artifacts, CI and root
docs. A writer needing another owner's file sends a concrete proposal; the
coordinator either applies it or transfers ownership before editing starts.
Backend may write a migration only after the coordinator allocates its revision
and parent and transfers that specific path. Preserve one Alembic head.

## Task and handoff contracts

A task packet contains:

```text
Task ID / objective / acceptance criteria / normative references
Approved base SHA / branch / absolute worktree path / role
Exclusive allowed files / shared-file owner / forbidden scope
Required incoming interfaces / outgoing schemas, ports and errors
Database name / PostgreSQL port / runtime owner / reserved host ports
Focused tests / relevant final gates / commit and remote authorization
```

Use concrete paths, not overlapping wildcards. A dependency handoff contains the
public interface, synthetic examples, error/ETag semantics, revision/document
versions and the approved base SHA. Mark unresolved decisions explicitly.
Frontend can review existing consumers and prepare tests while an API changes;
code depending on new types waits for the generated-contract handoff. Milestone 2
includes client types and contract consumption, with authoring UI reserved for M6.

Return a concise handoff with changed files, candidate SHA or uncommitted content
fingerprint, exact commands/results, migration SQL/up/down evidence, contract drift,
security findings, pending dependencies and remaining risks. Passing focused tests
does not imply PostgreSQL or Compose acceptance passed.

## Parallelism and integration

Safe parallel work: independent read-only audits; frontend consumption of a frozen
contract while backend implements another slice; QA acceptance tests in exclusively
owned files; pure validators against agreed interfaces while project persistence
is built. Backend submodules can be split only when their ports and write sets are
fixed. This does not require a fifth agent.

Sequential work: decide compatibility surfaces, land shared transaction/revision
contracts, allocate the next migration, integrate model registration and API
wiring, regenerate contracts, then verify the integrated result. Suites depend on
test revision persistence. Only the coordinator integrates a candidate; dependent
writers use that integrated base, not each other's partially edited checkouts.

Integration gates:

1. Scope and ownership match the packet; no unagreed architecture decision.
2. Focused TDD evidence and relevant local gates pass on the candidate being reviewed.
3. Independent review covers transactions, concurrency, privacy and compatibility;
   findings include file/line, consequence and reproducible evidence.
4. Coordinator integrates one reviewed slice, regenerates types once, and runs
   PostgreSQL/migration and contract gates on that combined candidate.
5. Run full-stack acceptance at milestone/infrastructure boundaries. After an
   authorized push, all existing backend/frontend/compose CI jobs must pass for
   the exact resulting SHA. Review findings and CI failures must be resolved or
   explicitly reported; a reviewer is not a substitute for tests.

Authorization is independent of test success. This workflow does not authorize
committing, pushing, merging, opening PRs or changing repository settings. Follow
the user's current authorization; local drafts and reversible work can proceed.

## Worktrees and branches

Prefer the installed app's **Worktree** mode or the CLI's verified `--worktree`
option for a new isolated session. Check its actual working directory and HEAD;
managed worktrees may begin detached. Use one worktree per writer and a separate
integration worktree. Never assume spawned agents automatically get isolation:
the collaboration tools in this session share the checkout unless directed to a
different absolute worktree path. Read-only reviews may share the checkout.

Native managed worktrees own their placement/lifecycle. For explicitly named
manual worktrees, use `.worktrees/<task>` (ignored by Git and Docker) with the
following Git fallback. Never combine a managed session with a second manual
worktree for that same task. Never force-remove a worktree with pending changes.

Branches use the task and milestone, for example `feat/m4-<slice>`,
`test/m3-acceptance`, or `fix/m3-<defect>`. A short-lived integration branch is
useful only when several reviewed slices must be combined; otherwise each slice
targets `main`. No permanent backend/frontend branches. Keep PRs scoped to one
acceptance outcome; the coordinator controls integration order and migration IDs.

Git shares refs and object storage across worktrees. Serialize commit/rebase/merge
and branch-management operations. Do not copy `.env`, secret stores, `.venv` or
`node_modules` into another task; install locked dependencies per worktree.
Do not add `.worktreeinclude` entries for secrets.

## Runtime isolation

Worktrees isolate files, not databases, ports or `/tmp`. Each writer's PostgreSQL
tests use a dedicated disposable `<task>_test` database. The fixtures clean
catalog, job, execution, and attempt state, so do not run concurrent suites in one
database or enable pytest parallel workers with shared fixtures. Migration
downgrade uses a newly created disposable database only.

Initially assign one full Compose runtime owner. `-p` isolates project resources
and volumes but does **not** replace the fixed published ports. Concurrent stacks
require reviewed port overrides and corresponding health/proxy URLs. Use one
native worker runtime at a time: `/tmp/sentinel-worker-health` is currently shared.
Never stop another task's stack or prune shared Docker volumes. The
[quality reference](quality-gates.md) includes an isolated PostgreSQL recipe.

## Starting parallel work

Use the current milestone plan and accepted contract to define the next slice.
New worktrees do not inherit uncommitted files, so start from the exact reviewed
base or explicitly transfer the reviewed changes.

1. Coordinator checks `git status --short --branch`, `git remote -v`,
   `git worktree list`, and records `git rev-parse HEAD` as the common base.
   Reconcile any unrelated changes before proceeding; never reset them.
2. Open isolated app sessions or manual worktrees based on that SHA. Use fresh
   task-specific branch/path names, inspect existing worktrees before creation,
   and never force-remove a worktree with pending changes.
3. In each writer worktree run `make setup`, then its relevant fast gate. Reserve
   the database and ports in the task packet. Generated-contract consumers wait
   for the coordinator-owned integrated contract.
4. With collaboration tools, coordinator sends each agent the packet including
   its absolute path and instructions to use that directory for every command.
   A read-only reviewer can start immediately. Without spawn tools, use separate
   app/CLI sessions in the same designated worktrees; there is no required custom
   agent-role TOML configuration or shell `codex spawn` command.
5. Follow the current plan's dependencies, integrate reviewed slices in order,
   regenerate shared contracts once, and run the combined gates. Commits, pushes,
   and merges wait for authorization.

## Repository skills

Explicit invocation examples: `$sentinel-feature`, `$sentinel-quality-gate`,
`$sentinel-security-review`, `$sentinel-pr-prepare`. They live under
`.agents/skills/`, the documented repository discovery location. Start a new
session after adding skills if the current catalog does not refresh; reading the
named `SKILL.md` explicitly also works. No global Codex configuration is changed.

Capability evidence: local `codex --version` reported **0.160.1**;
`codex features list` reported `multi_agent` and `worktrees` stable/enabled;
`codex --help` exposed `--worktree`/`-C`, and `codex review --help` exposed
`--uncommitted`/`--base`. This session provides spawn/message/wait tools and four
concurrent slots including the coordinator. Treat these as observed capabilities,
not requirements for every installation. Official references:
[skills](https://learn.chatgpt.com/docs/build-skills),
[subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees).
