# Milestone 3 implementation handoff

Status: M3-00 architecture and security contract **FROZEN** on 2026-10-17;
production implementation is not authorized. Milestone 2 is accepted with status
**PASS** at
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
  [ADR 0008](../architecture/ADRs/0008-http-dispatch-outcomes-and-tls-policy.md)
  extends ADR 0007 with the frozen transport-failure, certainty, redirect, TLS,
  trust, proxy, and DNS-pinning rules.
- The frozen [Milestone 3 implementation packet](../implementation/milestone-3.md)
  and [task plan](milestone-3-plan.md) control M3 compatibility surfaces and slice
  ownership.
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

## Resolved M3-00 contracts

1. A known durable transport/redirect failure uses terminal attempt state
   `transport_failed`. `DispatchCertainty` distinguishes `not_started`, positively
   proven `not_sent`, `possibly_sent`, and `response_received`.
2. The `dispatching` checkpoint commits `possibly_sent` before DNS. Only positive
   controlled pre-write phase evidence under a live fenced lease may record
   `not_sent`; exceptions, cancellation, lease loss, process death, or uncertain
   commit do not.
3. A received `3xx` is an accepted response when redirects are disabled. When an
   enabled safe-method redirect hop is rejected, the attempt is
   `transport_failed`/`redirect_denied` with `response_received` certainty, the
   preceding response is sanitized evidence, and no connection reaches the
   rejected hop.
4. HTTPS verification is mandatory with TLS 1.2 or newer. Existing
   `verify_tls: false` definitions stay readable but fail before DNS/socket I/O.
   Trust is default roots plus an optional deployment-wide additive CA bundle;
   proxy inheritance, mTLS, early data, insecure mode, and target pooling are out
   of MVP scope.
5. The locked HTTPX/httpcore stack can dial a selected IP while retaining the
   original authority and SNI/hostname verification through a narrow
   version-qualified adapter seam. M3-03 must prove the behavior locally before
   feature code; dependency upgrades require requalification and may not fall
   back to hostname re-resolution.
6. Execution, item, attempt, artifact, idempotency, and job transaction boundaries
   are frozen in the M3 packet. Queue delivery, attempt sequence, redirect hops,
   and trace retries remain distinct.
7. First-required-baseline bootstrap and baseline-selection timing remain M4
   decisions. M3 does not invent baseline semantics.

A material change to these contracts requires an ADR/product update before
implementation. Runtime OpenAPI and generated clients are published only with
implemented slices.

## Approved delivery sequence

This is a handoff sequence, not implementation authorization. The coordinator
must turn each approved slice into a task packet with an exact base SHA, branch,
worktree, owned files, database, ports, interfaces, tests, and publication
permissions.

1. **M3-00 — Freeze execution contracts and recovery cases.** Complete. ADR 0008,
   the M3 packet, named acceptance cases, transaction boundaries, and migration
   reservations are documented; publication remains separately authorized.
2. **M3-01 — Atomic execution creation and immutable materialization.** Persist
   executions/items/idempotency records, pin all source revisions in one
   transaction, enqueue atomically, and add POST/list/detail contracts without
   dispatching a target request.
3. **M3-02 — Request preparation and protected observations.** Add template
   expansion, in-memory secret resolution, request fingerprinting, bounded capture,
   and redaction-before-persistence with synthetic canary coverage.
4. **M3-03 — Safe HTTP adapter.** First pass the locked-stack selected-IP,
   authority, SNI, hostname, retry/proxy, and connection-isolation feasibility
   gate; then enforce DNS/address and redirect-hop validation, credential stripping
   across origins, TLS policy, timeout/size limits, streaming, and bounded
   concurrency through explicit ports.
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

The contract decisions required for M3-01 are resolved. The next coordinator may
prepare an M3-01 task packet from the accepted base only after the M3-00
documentation candidate is reviewed/published and explicit production
implementation authorization is supplied. M3-03 has the additional mandatory
transport feasibility gate. No current authorization permits M3-01, a migration,
runtime OpenAPI generation, a commit, or a push.
