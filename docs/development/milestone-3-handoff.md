# Milestone 3 planning handoff

Status: planning handoff only. Milestone 2 is accepted with status **PASS** at
`6b83adf0b8c9d9dcb0bba668a9e15d8ff0b4d715` on `main`. This document does not
authorize Milestone 3 implementation, a commit, a push, a merge, a migration, or
a change to an accepted architectural contract.

The repository owner supplied the accepted remote evidence for that SHA:
[GitHub Actions run 38971960329](https://github.com/amnotwallas/sentinel/actions/runs/38971960329),
triggered by a push to `main`, concluded `success` in 1 minute 28 seconds. The
explicit frontend detail was 2 Vitest files and 9 tests passed. The run was not
independently retrieved, and individual backend and Compose job conclusions were
not separately supplied.

## Normative inputs

- [AGENTS.md](../../AGENTS.md), [MVP](../MVP.md), the
  [Milestone 3 roadmap scope](../ROADMAP.md#milestone-3-safe-execution-lifecycle-and-http-adapter),
  [architecture](../architecture/README.md), and accepted ADRs remain authoritative.
- ADR 0002 governs PostgreSQL at-least-once job delivery and lease fencing; ADR
  0005 governs per-attempt OpenTelemetry identity; ADR 0006 governs secrets,
  redaction, and persistence; ADR 0007 governs dispatch checkpoints, replay, target
  validation, redirects, TLS, timeouts, capture limits, and bounded concurrency.
- The [Milestone 2 implementation packet](../implementation/milestone-2.md) and
  planned OpenAPI/fixtures contain reviewed future-interface inputs only. They do
  not make unimplemented M3 routes or schemas part of the runtime contract.
- Use the [development workflow](workflow.md) for ownership and isolation and the
  [quality gates](quality-gates.md) for verification evidence.

## Incoming implemented foundation

- M1 provides the durable PostgreSQL job queue, bounded delivery, lease heartbeat,
  expiration recovery, and stale-token fencing.
- M2 provides immutable project/environment/test/suite inputs, exact suite revision
  pins, canonical request policies, secret references, strong ETags, change
  history, active OpenAPI generation, and typed frontend client consumption.
- Runtime APIs contain health and the 16 M2 catalog operations only. No execution
  endpoint, target HTTP dispatch, secret resolution, result evaluation, baseline
  behavior, or Tempo reconciliation is implemented by this handoff.

## Milestone 3 outcome and boundaries

Milestone 3 must execute one test or ordered suite from `POST /api/v1/executions`
to a durable, bounded, redacted observation while preserving deterministic crash
recovery. It includes execution/idempotency persistence, revision pinning, request
preparation, in-memory secret resolution, the safe HTTP adapter, attempt trace
identity/checkpointing, resumable orchestration, and execution/attempt reads.

It does not include baseline comparison/promotion (M4), Tempo reconciliation and
linked-trace discovery (M5), authoring/results UI (M6), scheduling, notifications,
multi-tenancy, billing, AI analysis, Kubernetes, or a dedicated broker. Missing
telemetry must not alter functional execution outcomes.

## Decisions required before compatibility surfaces

1. Define the durable attempt transition and observation checkpoint for a
   transport failure that produces no HTTP response. The M2 planning schema
   identifies this gap; no implementer may silently add or reinterpret an attempt
   state.
2. Define and document the operator deployment policy, startup validation, and
   test matrix governing any explicit `verify_tls: false` definition. TLS
   verification remains on by default and a stored opt-out is not permission by
   itself.
3. Freeze the execution, item, attempt, artifact, idempotency, and job transaction
   boundaries before allocating migrations or publishing runtime OpenAPI. Queue
   delivery count, HTTP attempt sequence, and trace-correlation retries remain
   distinct.
4. Keep the first-required-baseline bootstrap and baseline-selection timing open
   for the M4 product/ADR decision. M3 may persist the immutable execution inputs
   needed later but must not invent baseline semantics.

A material change to an accepted ADR or MVP contract requires the documented ADR
and product update before implementation.

## Proposed delivery sequence

This is a handoff sequence, not implementation authorization. The coordinator
must turn each approved slice into a task packet with an exact base SHA, branch,
worktree, owned files, database, ports, interfaces, tests, and publication
permissions.

1. **M3-00 — Freeze execution contracts and recovery cases.** Resolve the two M3
   decisions above, enumerate every durable checkpoint and recovery result, close
   API/problem/idempotency contracts, assign migrations, and name acceptance cases.
2. **M3-01 — Atomic execution creation and immutable materialization.** Persist
   executions/items/idempotency records, pin all source revisions in one
   transaction, enqueue atomically, and add POST/list/detail contracts without
   dispatching a target request.
3. **M3-02 — Request preparation and protected observations.** Add template
   expansion, in-memory secret resolution, request fingerprinting, bounded capture,
   and redaction-before-persistence with synthetic canary coverage.
4. **M3-03 — Safe HTTP adapter.** Enforce DNS/address and redirect-hop validation,
   credential stripping across origins, TLS policy, timeout/size limits, streaming,
   and bounded concurrency through explicit ports.
5. **M3-04 — Resumable dispatch and recovery.** Persist `dispatching` before I/O,
   create per-attempt trace/span identity, checkpoint responses, separate job
   redelivery from HTTP replay, and implement conservative ambiguous recovery.
6. **M3-05 — Execution and attempt reads plus typed client handoff.** Publish only
   implemented runtime schemas, regenerate artifacts once under coordinator
   ownership, and verify bounded redacted outputs.
7. **M3-06 — Independent acceptance and milestone integration.** Exercise single
   tests and ordered suites, termination at every checkpoint, ambiguity/replay,
   target-policy attacks, privacy sinks, PostgreSQL/migration/contract gates, full
   Compose, and final CI on the exact integrated SHA.

## Ownership and verification handoff

- The coordinator owns shared API/worker wiring, model registration, migration
  allocation and chain, fixture cleanup, generated OpenAPI/client artifacts,
  milestone documentation, integration, and final evidence.
- Start with one backend writer for the transaction/state-machine critical path.
  Split request preparation and the HTTP adapter only after their ports, shared
  types, and write sets are frozen. A security/QA reviewer is read-only unless
  assigned exclusive acceptance files.
- Use fresh isolated worktrees from the accepted base, separate disposable
  `_test` databases, and reserved ports. Do not reuse the long-lived M2 worktrees
  as evidence for an M3 candidate.
- Apply test-driven development to every production slice. Run focused tests,
  backend/frontend/contract gates as applicable, real PostgreSQL and migration
  round trips for persistence, security review for request/secret/network paths,
  and the task-owned full Compose gate at integration.
- A final M3 PASS requires the exact integrated candidate identity, complete local
  evidence, independent review resolution, and remote CI evidence under the
  workflow rules. Test success never grants commit, push, merge, or remote-setting
  permission.

## Start condition

The next coordinator may prepare the detailed M3-00 contract/task packet from
this handoff. Production implementation starts only after explicit authorization
and after the open transport-failure and TLS-policy decisions are resolved or
assigned as the authorized contract-freeze work.
