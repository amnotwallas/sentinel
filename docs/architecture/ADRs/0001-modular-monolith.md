# ADR 0001: Modular monolith with separate API and worker processes

- Status: Accepted
- Date: 2026-10-09

## Context

Sentinel needs an interactive control plane and a failure-isolated execution
plane. API tests can block on DNS, TLS, target timeouts, response processing, and
trace ingestion. Running them in a FastAPI request handler would couple UI
availability to target behavior and would lose in-flight work on API restart.

The MVP is single-user and local-first. Independent backend services would add
network contracts, deployment ordering, distributed transactions, and operational
burden before the product has scaling evidence.

## Decision

Use one Python codebase, one PostgreSQL schema, and two runtime entry points:

- the `api` process validates transport input and invokes application services;
- the `worker` process leases durable jobs and invokes the same application
  services for execution and trace reconciliation.

Domain capabilities are separated into `catalog`, `execution`, `regression`,
`telemetry`, and `security` modules with explicit application-service boundaries.
FastAPI, worker polling, SQLAlchemy, HTTPX, and Tempo/OpenTelemetry implementations
are outer adapters. Modules communicate in process and may participate in one
database transaction; they do not call internal HTTP services.

The frontend is a separate React build because it has a distinct toolchain and
runtime, not because the backend is a service mesh.

## Alternatives considered

### Execute inside FastAPI

This minimizes processes but makes request duration, restart recovery, and
bounded concurrency unsafe. FastAPI background tasks are not a durable queue.

### Backend microservices

This gives independent deployment and scaling but adds failure modes and
infrastructure with no MVP need. The modules can be extracted later only if
measured load or team ownership requires it.

### Separate worker repository/package

This creates version skew between queue payloads and handlers. Sharing the domain
and application package gives one compatibility boundary while keeping process
failure isolation.

## Consequences

- The API stays responsive while target requests run or fail.
- API and worker releases must use compatible code and migrations.
- Module boundaries require review because the language/runtime does not enforce
  deployment isolation.
- PostgreSQL is a shared failure domain for the control and execution planes.
- Individual modules cannot be scaled or released independently. This is an
  accepted MVP constraint.

## Guardrails

- API routes may not perform target HTTP calls.
- Worker entry-point code may not contain domain classification rules.
- Cross-module writes use application services, not another module's ORM models.
- A proposal to split a service requires measured evidence, a migration path,
  and a superseding ADR.
