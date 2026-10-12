---
name: sentinel-quality-gate
description: Use when validating a Sentinel change, selecting local or PostgreSQL checks, checking generated-contract drift, or preparing milestone verification evidence.
---

# Sentinel quality gate reference

Run from the assigned worktree root. Exact commands, isolated PostgreSQL/Compose
setup and cleanup are in [quality gates](../../../docs/development/quality-gates.md).
Use existing CI as the required final gate; local wrappers are convenient subsets.

| Change | Local gate |
| --- | --- |
| Backend | Focused behavior tests, then `make check-backend` |
| Frontend | Focused Vitest tests, then `make check-frontend` |
| API/client | `make check-contract` plus backend/frontend gates |
| Persistence/concurrency | Dedicated PostgreSQL database, full pytest and migration SQL/up/down/drift recipe |
| Infra/runtime/milestone | `make check-compose-config` and task-owned full Compose recipe |
| Checker | `make check-tooling` and injected drift/missing-input verification |

`make setup` installs locks. `make check-fast` runs non-DB backend, frontend,
contract and tooling checks. It does not run PostgreSQL, migrations or containers.
`make check-contract` compares temporary generation against candidate artifacts;
it does not overwrite or fix drift. Regeneration is a separate coordinator-owned
mutation described in the reference.

Example: a revision-persistence slice uses a new `m2_environments_test` database,
reserved PostgreSQL port and full migration/full-suite recipe. Record SQL/head,
concurrent update results and rollback tests. Never share the database with another
suite: fixtures delete rows. A `_test` suffix alone does not authorize destroying
existing data. Downgrade and volume deletion use only newly created disposable
resources. A project name alone does not isolate fixed Compose ports.

Test commands remove the runtime token/host; contract subprocesses remove all
`SENTINEL_*` values. Keep other runtime settings out of the test shell and do not
print secrets while diagnosing failures. Investigate environment contamination
before changing expectations or disabling checks.

Evidence: candidate/base identity, exact commands/exit results and test counts,
database/runtime isolation, migration/head/SQL, drift and skipped gates with
reasons. After an authorized push, record the exact SHA/run URL and backend,
frontend and Compose job results. Changed candidate contents require affected
checks again; historical M1 success is not current verification.
