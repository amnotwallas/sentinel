# Sentinel

Sentinel is an open-source, self-hosted API reliability and distributed tracing
platform. This repository currently implements **Milestone 1: Repository
Foundation and Durable Work Skeleton**. It provides a FastAPI health API, durable
PostgreSQL queue, worker probe handler, React shell, migrations, and CI.

Product definitions and outbound HTTP test execution begin in later milestones.
The internal probe sends no target requests and produces no functional test
verdict.

## Prerequisites

- Docker Engine/Desktop with Docker Compose v2.20 or newer for the full stack.
- Python 3.12 and uv for native backend development.
- Node 22.12 or newer in the Node 22 release line and npm for frontend development.
- PostgreSQL 16 for native integration tests. CI uses real PostgreSQL 16.

See [the approved MVP](docs/MVP.md), [architecture](docs/architecture/README.md),
[ADRs](docs/architecture/ADRs/), [roadmap](docs/ROADMAP.md), and
[engineering guide](AGENTS.md).

## Start with Docker Compose

From the repository root:

```sh
cp .env.example .env
openssl rand -hex 32
```

Paste the generated value into `SENTINEL_API_TOKEN` in `.env`. The container API
listens on its internal non-loopback interface, so the token guard applies even
though published host ports are loopback-only. Use a different database password
before sharing a machine; use a URL-safe value or percent-encode credentials in a
native database URL. Keep `.env` private and uncommitted.

```sh
docker compose --env-file .env -f infra/compose.yaml config --quiet
docker compose --env-file .env -f infra/compose.yaml up -d --wait postgres
docker compose --env-file .env -f infra/compose.yaml run --build --rm api alembic upgrade head
docker compose --env-file .env -f infra/compose.yaml up -d --build --wait --wait-timeout 180
```

Open `http://127.0.0.1:5173`. The API is at `http://127.0.0.1:8000` and Tempo's
readiness endpoint is at `http://127.0.0.1:3200/ready`. Tempo is included because
Milestone 1 explicitly requires it; Sentinel trace correlation arrives later.
No Grafana UI, Collector, Redis, or message broker is required.

```sh
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
docker compose --env-file .env -f infra/compose.yaml exec -T api python -m sentinel.worker.smoke
docker compose --env-file .env -f infra/compose.yaml logs --tail 100 worker
```

The bounded smoke command inserts a probe transactionally and waits for the
running worker to finish it. Health endpoints are public and contain no secret
configuration; `/docs` and `/openapi.json` require the configured bearer token.
Swagger's page itself also requires authorization, so prefer a client that can
send the header when using a token-protected installation.

```sh
docker compose --env-file .env -f infra/compose.yaml stop tempo
curl --fail http://127.0.0.1:8000/health/ready
docker compose --env-file .env -f infra/compose.yaml start tempo
docker compose --env-file .env -f infra/compose.yaml down
```

Stopping Tempo leaves PostgreSQL-backed API readiness available, with
`tempo: unavailable`. `down` preserves named PostgreSQL and Tempo volumes. Do not
add `--volumes` unless intentionally deleting local data.

## Native backend development

```sh
uv sync --project backend --frozen
uv run --env-file .env --project backend alembic -c backend/alembic.ini upgrade head
uv run --env-file .env --project backend sentinel-api
```

In another terminal:

```sh
uv run --env-file .env --project backend sentinel-worker
uv run --env-file .env --project backend sentinel-probe
uv run --env-file .env --project backend python -m sentinel.worker.smoke
```

Native API binding defaults to `127.0.0.1`; non-loopback binding requires a bearer
token. The native worker is one process with one active handler. The API and
worker import the same installed package. Neither runs schema migrations
automatically. Readiness compares the database revisions with the single head in
the deployed Alembic migration graph. It returns `503` for missing or mismatched
revisions, missing/ambiguous migration assets, or a connection failure. Run
migrations explicitly before starting workers; readiness never executes them.

## Frontend development

```sh
cd frontend
npm ci
npm run dev
```

Vite listens on `127.0.0.1:5173` and proxies health/API paths to
`http://127.0.0.1:8000`. `SENTINEL_API_PROXY` overrides that server-side proxy URL
for Compose. Never use `VITE_` environment variables for secrets; those values
become browser assets. The shell does not resolve credentials or expose product
authoring workflows.

## Migrations

```sh
uv run --env-file .env --project backend alembic -c backend/alembic.ini current
uv run --env-file .env --project backend alembic -c backend/alembic.ini upgrade head
uv run --env-file .env --project backend alembic -c backend/alembic.ini check
uv run --project backend alembic -c backend/alembic.ini upgrade head --sql
```

Review the generated SQL before applying schema changes. For a new schema change,
use `alembic revision --autogenerate -m "description"` from `backend/`, review
the migration, and update the models/tests together. The initial schema contains
only `executions` (internal probe envelopes) and `jobs`; catalog/revision fields
and other subject types will be introduced by later migrations.

Downgrade `0001` removes the two tables and their probe/queue data. Verify
downgrade only in a disposable test database, or take a backup and explicitly
accept data loss first:

```sh
uv run --project backend alembic -c backend/alembic.ini downgrade base
uv run --project backend alembic -c backend/alembic.ini upgrade head
```

Set `SENTINEL_DATABASE_URL` to the disposable database before these commands.

## Run checks

Create a dedicated `sentinel_test` database. For the local Compose PostgreSQL:

```sh
docker compose --env-file .env -f infra/compose.yaml exec -T postgres createdb -U sentinel sentinel_test
```

Migrate the test database separately, using its connection string:

```sh
SENTINEL_DATABASE_URL=postgresql+psycopg://sentinel:sentinel-local-only@127.0.0.1:5432/sentinel_test \
  uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --env-file .env --project backend pytest backend/tests
uv run --project backend ruff check backend
uv run --project backend ruff format --check backend
cd backend
uv run mypy
```

Adjust credentials to match `.env`. `SENTINEL_TEST_DATABASE_URL` must identify a
database whose name ends in `_test`. Tests delete only `jobs` and `executions` in
that dedicated database before each integration test. Never point tests at a
database whose data you want to retain. Missing database configuration fails the
suite instead of silently skipping integration tests. Unit/contract-only runs
use `pytest -m 'not integration'`.

```sh
cd frontend
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
```

Generate the frontend contract from the installed backend, from the root:

```sh
uv run --project backend python -m sentinel.api.export frontend/openapi.json
cd frontend
npm run api:generate
```

Both `frontend/openapi.json` and `frontend/src/shared/api/generated/schema.ts`
are committed artifacts. CI regenerates them and rejects drift. The initial
contract contains only health endpoints.

GitHub Actions runs backend lint/type/tests with PostgreSQL, migration
up/down/drift checks, frontend checks/build, contract generation, rendered Compose
port validation, and a full Compose worker smoke run.

For local feedback, `make setup` installs locked dependencies and `make check-fast`
runs backend non-integration, frontend, developer-tooling and non-mutating contract
checks. See [quality gates](docs/development/quality-gates.md) for PostgreSQL and
Docker acceptance, [development workflow](docs/development/workflow.md) for agent
ownership/worktrees, and [Milestone 2 planning](docs/development/milestone-2-plan.md).

## Operations and limitations

See [durable work operations](docs/operations/durable-work.md) for transaction
boundaries, lease ownership, retry behavior, failure modes, and queue limitations.

This milestone has no public enqueue endpoint. `sentinel-probe` and the smoke
command are internal verification tools. No target HTTP calls, test definitions,
baseline comparisons, or trace correlation are implemented yet.
