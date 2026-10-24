# Milestone 6 UI handoff

Status: **M5 complete; M6 preparation only**.

This handoff starts from accepted M5 implementation SHA
`18d72162c26575778ab94556d0f85c2c76ecc75d`. It records the backend and typed
API capabilities available to the UI, the frozen Milestone 6 boundaries from
the roadmap, and decisions that must be resolved before implementation. It
does not authorize backend changes, new API routes, M7 work, or UI coding.

## Existing backend and API capabilities

The current versioned API is described by [frontend/openapi.json](../../frontend/openapi.json)
and [generated TypeScript](../../frontend/src/shared/api/generated/schema.ts).
The available `/api/v1` surfaces are:

- Projects: list, create, and read.
- Environments: project-scoped list/create and read/update.
- Test cases: project-scoped list/create and read/update, revisions, baselines,
  and baseline activation.
- Suites: project-scoped list/create and read/update.
- Executions: create, list/filter, and detail reads.
- Attempts: persisted attempt-detail reads at
  `GET /api/v1/attempts/{attempt_id}`.
- Health: liveness and readiness.

Attempt detail already exposes lifecycle state, functional verdict, dispatch and
transport outcomes, observations, assertions/evaluations, baseline comparison,
promotion eligibility, change evidence, legacy primary trace/span fields, and
the additive M5 `trace_references` array.

M5 trace-reference UI data is persisted evidence only. Each reference includes
relation, canonical trace identity, indirect/direct provenance, correlation
status, lookup timestamps/counts, bounded evidence, and an optional validated
operator Tempo link. References are ordered primary first, then linked, and are
bounded to 17. The UI must not query Tempo directly or infer classifications,
causes, parentage, or verdict changes.

## Frozen Milestone 6 scope

The roadmap defines M6 as the MVP user interface:

- project/environment setup and versioned test/suite authoring;
- execution start, polling, filtering, and history;
- attempt detail with lifecycle, verdict, assertions, selected baseline diffs,
  performance warnings, transport outcomes, and truncation/redaction notices;
- baseline eligibility review, explicit promotion confirmation, history, and
  compatible rollback;
- trace states, direct/indirect provenance, Tempo links, and missing/partial
  explanations;
- definition/baseline/deployment evidence timeline using backend-provided facts;
- keyboard-accessible controls, focus management, semantic status text, and
  non-color-only verdict indicators.

The M6 exit criteria are a complete browser MVP journey, no UI-invented
classification or causal language, and zero frontend/OpenAPI drift. The M5
non-goals remain in force: no trace UI was implemented in M5, no refresh route
was added, and no full trace store or root-cause feature is approved.

## Proposed implementation boundaries

The initial M6 write set should be limited to frontend feature code, styles,
typed API-client usage, fixtures, and frontend tests. It should consume the
existing generated contract and existing backend routes. Backend, migration,
OpenAPI, and generated-client changes are out of scope unless a separately
approved M6 decision identifies a concrete contract gap.

The UI should:

- keep server state in a query/cache layer and use typed generated models;
- poll execution state only while execution is non-terminal, then refresh
  attempt detail independently when persisted trace reconciliation may continue;
- render `pending`, `missing`, `available`, `partial`, `tempo_unavailable`, and
  `expired` without changing the functional verdict;
- distinguish `sentinel_context` from `baggage_attribute_search` provenance;
- show bounded evidence and safe links only when supplied by the API;
- preserve explicit confirmation for unsafe replay and baseline promotion; and
- keep secrets, internal Tempo URLs, raw telemetry, and unapproved attributes
  out of browser state and rendered output.

## Existing frontend starting point

The current frontend is a small React/Vite shell centered on
`frontend/src/App.tsx`, with the shared API client under
`frontend/src/shared/api/` and generated types under
`frontend/src/shared/api/generated/`. M6 should organize additions by the
existing product areas (`catalog`, `executions`, `baselines`, and `traces`) as
they are introduced, while keeping shared transport primitives under
`src/shared`.

## Decisions required before M6 implementation

The frozen roadmap does not yet specify these interaction details. They must be
resolved before coding rather than inferred:

1. primary navigation and route structure for catalog, authoring, executions,
   attempt investigation, baselines, and trace evidence;
2. query/cache library and polling intervals consistent with execution and
   independently updating reconciliation state;
3. exact empty, loading, error, pagination, and stale-data behavior for the
   existing cursor-based catalog and execution reads;
4. presentation and copy for every correlation state, including linked-only,
   multiple-linked, missing, partial, expired, and Tempo-unavailable cases;
5. how the UI handles a null or operator-only Tempo link without exposing the
   internal Tempo base URL;
6. baseline promotion, rollback, unsafe replay, and confirmation flows using
   the existing API contracts; and
7. accessibility test scope, fixture coverage, and the supported browser/layout
   baseline for the main author-run-investigate-promote journey.

If any decision requires a new endpoint, persisted field, generated contract,
verdict rule, or accepted architectural behavior, stop the UI slice and obtain
an explicit scope/contract update first.

## M5-to-M6 risks and prerequisites

- The M5 acceptance environment recorded two moderate npm audit warnings during
  `npm ci`; dependency ownership should evaluate them before release work.
- Tempo indexing and retention remain operational dependencies for the freshness
  of linked evidence, but the UI must remain correct with stored missing,
  partial, expired, or unavailable states.
- M7 still owns retention execution, deletion behavior, restartability, and the
  release-wide privacy scan.

No Milestone 6 implementation is accepted by this handoff. The next owner must
return with the resolved interaction decisions, a frontend-only write set, typed
fixtures covering the frozen API states, and the relevant accessibility and
contract verification plan.
