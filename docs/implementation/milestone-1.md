# Repository Foundation and Durable Work Skeleton Implementation Plan

> Historical execution: inline, using test-driven development and verification.
> Commits were not authorized during implementation. Work stayed in the supplied empty
> repository because it could not create a git worktree without a first commit.
> The implementation is now migrated to the cloned `amnotwallas/sentinel`
> repository on `main`; its README bootstrap commit is separate from this work.

**Goal:** Deliver Milestone 1 of `docs/ROADMAP.md`.

**Architecture:** Separate API and worker entry points share one Python package.
PostgreSQL owns queue durability; application checkpoints are fenced by leases.
An internal probe proves orchestration without any target HTTP execution.

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL,
OpenTelemetry, React, TypeScript, Vite, pytest, Vitest, Docker Compose.

**Spec:** `docs/ROADMAP.md`, `docs/MVP.md`, `docs/architecture/README.md`, and
accepted ADRs 0001–0007.

**Current acceptance status:** Milestone 1 is complete. Docker Desktop acceptance
passed on macOS on 2026-10-09 (local time). The authorized implementation commit
`62635ea71566dc8e21118667a393ed944f6a0cce` was pushed to `main`; the user confirmed
all three GitHub Actions jobs passed (backend 46s, frontend 24s, Compose 1m23s).
The run URL/logs have not been independently captured here; CI success is
user-reported. Earlier pending/daemon-unavailable reports below are historical
evidence, not current blockers. Milestone 2 has not started.

## Constraints and review focus

- Exactly 60-second default leases, 15-second heartbeats, 3 deliveries, and
  5/30-second retry delays; no broker or outbound test execution.
- Expired tokens are invalid even before another worker reclaims the row.
- A job failure and its execution failure must commit atomically.
- Database failure cancels active handler work; recovery relies on lease expiry.
- Production lease decisions use PostgreSQL time; tests inject time without sleeps.
- Raw exceptions/configuration must not expose credentials in logs or API errors.
- A lost notification cannot lose work because polling is authoritative.

## Tasks

- [x] Foundation: backend dependencies/lock, strict tooling, domain state tests,
  settings validation, typed clock and UUID ports.
- [x] Persistence: explicit Alembic initial schema for `executions` and `jobs`,
  session ownership, queue repository, fencing, claim and transition tests.
- [x] Worker: application service and probe, cancellable heartbeat and shutdown,
  polling, structured safe logging, boundary tracing, restart tests.
- [x] API: health/readiness, stable problem responses, safe bind settings,
  OpenAPI generation and contract tests.
- [x] Frontend: Vite shell, strict lint/type/format/test/build, OpenAPI types.
- [x] Infrastructure/CI/docs: five required Compose services, health checks,
  migrations, PostgreSQL CI, startup/check commands, smoke run and limitations.
- [x] Available local verification: migrations up/down/check, full PostgreSQL suite,
  backend/frontend checks, generated contract drift, Compose config/smoke where
  available, and final review.
- [x] Local Docker-enabled acceptance: image builds, all five container health
  checks, full-stack probe, Tempo-outage smoke, actual in-flight recovery/fencing,
  and named-volume persistence across PostgreSQL restart/replacement.
- [ ] GitHub Actions execution for this implementation. The GitHub remote now
  exists, but the implementation has not been committed or pushed; the roadmap's
  CI acceptance gate remains open. Later sections describing an absent remote or
  commit record the original checkout's historical state.

## Historical progress before Docker Desktop setup

- Source documents read; no architecture redesign required.
- Tempo included because the roadmap explicitly requires it in Milestone 1.
- Docker unavailable locally. PostgreSQL test binaries will be isolated from the
  product dependency graph; Compose execution remains subject to runtime access.
- PostgreSQL 16.2 was run from isolated test binaries under `/private/tmp`, with
  loopback access on port 55432. It is not a product dependency or committed asset.
- Initial test batches failed on missing implementation, then passed against the
  domain, queue, worker, API, and frontend code. A final malformed-authentication
  regression was reproduced and fixed using byte-safe constant-time comparison.
- Native API startup, liveness/readiness, worker health, and a durable probe through
  a separate running worker passed. The temporary API and worker were stopped.
- Migration downgrade/base -> upgrade/head and Alembic drift checks passed in the
  disposable test database.
- Standalone Compose 2.39.4 rendered the configuration successfully; the rendered
  port validator confirmed all published ports are loopback-only. The Docker daemon
  is absent, so image builds and container smoke/health checks are unverified here.
- npm 10 crashed resolving upgraded Vitest peers. npm 11.6.2 successfully refreshed
  the lockfile; a subsequent npm 10 `npm ci --offline --no-audit` passed. The patched
  dependency tree uses Vitest 4.1.11 and its audit reported zero vulnerabilities.
- The backend dependency audit exposed advisories in the initially selected
  Starlette release. FastAPI 0.143.0 and Starlette 1.7.0 are now locked; the final
  audit found no known vulnerabilities in auditable dependencies. The local
  Sentinel package is not on PyPI and cannot be assessed by that dependency audit.
- A heartbeat-error regression test reproduced an unexpected-error path marking
  work `dead`. All heartbeat errors now cancel the handler without checkpointing;
  the lease remains recoverable. Both infrastructure and unexpected error cases
  pass without sleeps.

## Verification evidence

Verified on 2026-10-09. Commands below run from the repository root unless a
working directory is specified. Temporary binaries, database files, and build
artifacts under `/private/tmp` are validation resources, not product dependencies.

### Backend and PostgreSQL

The dedicated PostgreSQL 16.2 instance used port 55432 and a disposable
`sentinel_test` database with loopback-only trust authentication. CI uses its own
password-protected PostgreSQL 16 service.

```sh
backend/.venv/bin/ruff check backend
backend/.venv/bin/ruff format --check backend
cd backend
.venv/bin/mypy
SENTINEL_TEST_DATABASE_URL=postgresql+psycopg://sentinel@127.0.0.1:55432/sentinel_test \
  .venv/bin/pytest tests -q
```

Results: Ruff passed; 35 Python files formatted; strict mypy passed over 33 source
files; **44 tests passed**. The suite includes 23 PostgreSQL integration cases and
21 unit/contract cases. An earlier full-suite invocation omitted the required
database variable and failed fixture setup (21 errors); the explicit configured
run above passed. Red-phase regressions intentionally failed before their fixes.

Each of these migration commands ran with
`SENTINEL_DATABASE_URL=postgresql+psycopg://sentinel@127.0.0.1:55432/sentinel_test`:

```sh
backend/.venv/bin/alembic -c backend/alembic.ini downgrade base
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
backend/.venv/bin/alembic -c backend/alembic.ini check
backend/.venv/bin/alembic -c backend/alembic.ini current
```

All exited successfully; drift check reported no new upgrade operations and
current revision was `0001 (head)`. Downgrade removed disposable test records only.

```sh
# Working directory: backend/
uv build --out-dir /private/tmp/sentinel-package-build
# Working directory: repository root
uvx pip-audit --path backend/.venv/lib/python3.12/site-packages
```

Wheel and source distribution both built successfully. The audit reported no
known vulnerabilities, with the local package excluded as noted above.

### Frontend and generated contract

From `frontend/`:

```sh
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
npm audit --audit-level=low --cache /private/tmp/sentinel-npm-cache
```

All passed. Vitest ran **1 passing shell test**; Vite built 29 modules. The audit
reported zero vulnerabilities. The generated artifacts were verified by running
the following generation cycle twice and comparing SHA-256 hashes (no drift):

```sh
backend/.venv/bin/python -m sentinel.api.export frontend/openapi.json
cd frontend
npm run api:generate
```

### Process and Compose checks

Native processes were started with the test database URL and API port 58000:

```sh
backend/.venv/bin/python -m sentinel.api.main
backend/.venv/bin/python -m sentinel.worker.main
cd frontend
npm run dev -- --port 5174
```

A bounded validation harness verified API liveness, PostgreSQL readiness with
Tempo unavailable, the frontend HTML response, `python -m sentinel.worker.smoke`,
and `python -m sentinel.worker.health`. All passed. The temporary API, worker,
frontend, and PostgreSQL processes were stopped after validation.

Standalone Docker Compose 2.39.4 was available as
`/private/tmp/sentinel-docker-compose`. With synthetic
`POSTGRES_PASSWORD=validation-only` and `SENTINEL_API_TOKEN=validation-only`:

```sh
/private/tmp/sentinel-docker-compose -f infra/compose.yaml config --quiet
/private/tmp/sentinel-docker-compose -f infra/compose.yaml config --format json \
  | backend/.venv/bin/python infra/check_bindings.py
/private/tmp/sentinel-docker-compose -f infra/compose.yaml ps
```

Configuration rendering and loopback-port validation passed. `ps` failed because
there is no Docker daemon at `/var/run/docker.sock`. Consequently no container
image build, container health check, full Compose smoke, or GitHub Actions run is
claimed to have passed. Milestone 1 is implemented but its Docker/CI exit gate
remains open; do not begin Milestone 2 until that gate is verified.

Repository hygiene: `git diff --check` passed, and a separate scan covered
untracked files for trailing whitespace and Markdown file links; all links
resolved. Compose, Tempo, and workflow YAML parsed successfully. No commits were
created.

## Acceptance follow-up: 2026-10-09

**Status: not fully accepted.** This follow-up rechecked the environment and ran
available checks. It did not execute containers or GitHub Actions. No production
code, workflow, architecture decision, or Milestone 2 functionality was changed.

### Docker and CI access evidence

At 23:32 UTC, `command -v docker` and `command -v gh` both returned exit status 1.
The following checked locations were absent:

- `/var/run/docker.sock`;
- `~/.docker/run/docker.sock`;
- `~/.colima/default/docker.sock`;
- `~/.orbstack/run/docker.sock`;
- `/Applications/Docker.app/Contents/Resources/bin/docker`;
- `/usr/local/bin/docker` and `/opt/homebrew/bin/docker`.

`DOCKER_HOST`, `DOCKER_CONTEXT`, `DOCKER_TLS_VERIFY`, and `DOCKER_CERT_PATH`
were unset. No Docker configuration or context metadata was found at the checked
standard locations. There is no configured alternative daemon endpoint to try.

The existing temporary standalone Compose binary reported version `v2.39.4`.
This command used synthetic credentials and returned exit status 1:

```sh
POSTGRES_PASSWORD=validation-only SENTINEL_API_TOKEN=validation-only \
  /private/tmp/sentinel-docker-compose -f infra/compose.yaml ps
```

Exact error: `Cannot connect to the Docker daemon at unix:///var/run/docker.sock.
Is the docker daemon running?` This is an unavailable runtime, not a successful
container test or a Docker API compatibility verification. No system software was
installed and no Docker volumes were accessed or deleted.

`git remote` returned no remotes, `git config --get-regexp '^remote\.'` returned
exit status 1, and `git log -1 --format=%H` reported that `main` has no commits.
The implementation remains untracked. Therefore no repository/run/commit can be
matched to this checkout for read-only CI verification. Credentials were not
enumerated. No commits, pushes, remote workflow triggers, or external changes
were made.

### Fresh verification results

The existing temporary PostgreSQL 16.2 binaries initialized a new disposable
cluster at `/private/tmp/sentinel-acceptance.nl36xg/data`, bound to `127.0.0.1:55433`.
Its dedicated database was `sentinel_acceptance_test`. Initial sandboxed startup
failed on shared-memory permissions; the approved unsandboxed retry succeeded.
This is **native PostgreSQL evidence**, not a containerized PostgreSQL result.

```sh
backend/.venv/bin/ruff check backend
backend/.venv/bin/ruff format --check backend
# Working directory: backend/
.venv/bin/mypy
SENTINEL_TEST_DATABASE_URL=postgresql+psycopg://sentinel@127.0.0.1:55433/sentinel_acceptance_test \
  .venv/bin/pytest tests -q
```

Ruff passed; 35 Python files were formatted; mypy passed over 33 source files;
**44 tests passed** (23 PostgreSQL integration cases and 21 unit/contract cases).
The full suite passed again after migration downgrade/re-upgrade. These include
atomic claiming, concurrent claims, expiration/recovery, stale ownership,
heartbeat cancellation, bounded retry exhaustion, and transaction rollback.
They do not prove a real Docker worker crash/restart.

With `SENTINEL_DATABASE_URL` set to the same dedicated connection string, these
commands exited successfully:

```sh
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
backend/.venv/bin/alembic -c backend/alembic.ini check
backend/.venv/bin/alembic -c backend/alembic.ini current
backend/.venv/bin/alembic -c backend/alembic.ini downgrade base
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
backend/.venv/bin/alembic -c backend/alembic.ini check
```

Revision was `0001 (head)` and both drift checks reported no new upgrade
operations. Only disposable test records were removed by tests/downgrade.
The temporary PostgreSQL process was stopped after verification; its files remain
under `/private/tmp`.

From `frontend/`, `npm run lint`, `npm run format:check`, `npm run typecheck`,
`npm test`, and `npm run build` all passed. Vitest ran **1 passing test** and Vite
built 29 modules. A structural comparison of the stored OpenAPI JSON with the
installed API's generated schema found no drift.

Compose configuration rendering and the loopback validator were repeated with
the synthetic credentials above and passed:

```sh
/private/tmp/sentinel-docker-compose -f infra/compose.yaml config --quiet
/private/tmp/sentinel-docker-compose -f infra/compose.yaml config --format json \
  | backend/.venv/bin/python infra/check_bindings.py
```

Leaving the API token empty, then leaving the PostgreSQL password empty, caused
configuration interpolation to reject each configuration (expected exit status
1). This verifies configuration guards only. Service DNS, container environment
delivery, actual host bindings, mount permissions, and persistence across
container replacement remain unverified.

### Workflow review

The workflow YAML parsed and its three jobs, `push`/`pull_request` triggers,
read-only repository permission, and PostgreSQL test service were checked.
Backend/frontend commands match the checks executed locally. The Compose job
explicitly migrates before application startup, waits for service health, runs a
worker probe, and verifies readiness during a Tempo outage. Cleanup uses `down`
without deleting volumes. No static configuration contradiction was identified.

This is not an Actions run or formal actionlint result: actionlint is not
installed. The current workflow has no explicit container restart/replacement,
in-flight lease recovery, or volume-persistence assertion. Its probe alone does
not close those acceptance checks. When runtime access is available, verify those
scenarios and preserve evidence before extending the Compose CI job to enforce
them; do not label its current checks as coverage they do not provide.

### Acceptance status matrix

| Mandatory check | Actual status |
| --- | --- |
| Docker image builds | Not executed; no accessible daemon |
| Complete Compose startup | Not executed; configuration rendering only passed |
| API/worker/PostgreSQL/frontend/Tempo container health | Not executed |
| Containerized PostgreSQL migrations | Not executed; native migrations passed |
| Durable worker lifecycle | Native PostgreSQL suite passed; container lifecycle unverified |
| Container restart/crash recovery and persistent data | Not executed |
| GitHub Actions execution for this implementation | Unverified; no remote or commit |

### Minimal Docker-enabled handoff

These are **pending commands**, not execution results. Run on a Docker-enabled
machine from this checkout. Configure `.env` using the README without overwriting
an existing file; generate a private bearer token and use a URL-safe database
password. Use a new acceptance project name to isolate volumes from an existing
Sentinel installation. Required host ports must be free; do not stop unrelated
services to free them automatically.

```sh
docker info
dc() { docker compose --env-file .env -p sentinel-m1-acceptance -f infra/compose.yaml "$@"; }
dc config --quiet
dc config --format json | python3 infra/check_bindings.py
dc build api worker frontend
dc pull postgres tempo
dc up -d --wait postgres
dc run --rm api alembic upgrade head
dc run --rm api alembic check
dc up -d --wait --wait-timeout 180
dc ps --all
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
curl --fail --output /dev/null http://127.0.0.1:5173/
dc exec -T api python -m sentinel.worker.smoke
dc restart api worker
dc up -d --wait --wait-timeout 180
dc exec -T api python -m sentinel.worker.smoke
dc stop tempo
curl --fail http://127.0.0.1:8000/health/ready
dc start tempo
dc up -d --wait --wait-timeout 180
```

Assert all five containers are healthy, readiness includes PostgreSQL available,
and the Tempo-outage response remains ready with `tempo: unavailable`. API
readiness and a completed probe demonstrate database service communication;
check the frontend's `/health/ready` proxy response too. Inspect actual container
port bindings and named-volume mounts, not only rendered configuration.

For lease/concurrency tests against **containerized** PostgreSQL, create a new
dedicated empty test database (commands assume the example `sentinel` user), then
use the native test runner; production images intentionally omit dev dependencies:

```sh
dc exec -T postgres createdb -U sentinel sentinel_acceptance_test
# Set both URLs to that new database using the actual URL-encoded password.
export SENTINEL_DATABASE_URL='postgresql+psycopg://sentinel:REPLACE_WITH_PASSWORD@127.0.0.1:5432/sentinel_acceptance_test'
export SENTINEL_TEST_DATABASE_URL="$SENTINEL_DATABASE_URL"
uv sync --project backend --frozen
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend pytest backend/tests -q
unset SENTINEL_DATABASE_URL SENTINEL_TEST_DATABASE_URL
```

Do not reuse a database containing user data: fixtures delete its probe/job rows.
The database test suite still does not substitute for real worker container
termination. Additional mandatory runtime evidence must show:

1. A committed probe remains present while the worker is stopped and after API
   restart; restarting the worker completes that **same job ID**.
2. An active probe handler is terminated after its lease/start checkpoint. A
   restarted worker reclaims after expiry with an increased delivery count/new
   token; the old token cannot heartbeat or complete. Use controlled failure
   injection and the clock port, not arbitrary sleeps or target HTTP calls.
3. The original job/execution records survive PostgreSQL container replacement
   with the same named volume. Do this only in the dedicated acceptance project;
   do not remove volumes or reset user data.

A fresh probe after `restart` verifies post-restart availability, not in-flight
recovery or survival of the original record. Keep these claims separate. The
default probe finishes too quickly for reliable mid-handler termination without
a test-only controlled handler; that acceptance harness is not yet present.

Use `dc down` to stop the dedicated stack when finished; never use `--volumes` or
volume pruning. Preserve command outputs and CI run/commit URLs when CI can be
observed. Creating a remote, committing/pushing this work, or triggering a remote
workflow requires separate authorization. Milestone 1 remains open until every
mandatory row above is verified and the roadmap's CI exit gate passes.

## macOS Docker Desktop acceptance: 2026-10-09

Verification completed on 2026-10-09 in `America/Mexico_City`; final checks ran
after 00:00 UTC on 2026-10-10. This section supersedes the earlier local Docker
blocker, without changing approved architecture or adding Milestone 2 behavior.
Only this ledger and the roadmap status note changed in the repository.

### Installation and runtime

- Host: macOS 27.0, build `26A425`, Apple Silicon `arm64`, 24 GiB RAM.
- Initially no Docker Desktop, Docker CLI, or accessible compatible daemon was
  present. The old standalone Compose binary did not provide a runtime.
- With explicit tool approval, Homebrew downloaded the official Apple Silicon
  Docker Desktop distribution and copied `/Applications/Docker.app`. The command
  was `HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1
  /opt/homebrew/bin/brew install --cask docker-desktop`.
- The system credential-helper link step requested a sudo password. Installation
  was interrupted without entering a password. The app remained installed;
  system CLI linking is incomplete. No alternative runtime was installed, no
  security setting was bypassed, and no additional system changes were made to
  work around that link step.
- Installed app version: **4.94.0**. Installer source:
  [official Docker macOS installation documentation](https://docs.docker.com/desktop/setup/install/mac-install/)
  and [Homebrew's Docker Desktop cask](https://formulae.brew.sh/cask/docker-desktop).
  Download: `https://desktop.docker.com/mac/main/arm64/241994/Docker.dmg`.
  SHA-256: `02147e4d559ff41e1d9d7be63a554101340237064c7b6df234548aa111ebf04c`.
- Approved, unsandboxed `codesign --verify --deep --strict --verbose=2
  /Applications/Docker.app` passed, and `spctl --assess --type execute --verbose
  /Applications/Docker.app` returned `accepted`, `Notarized Developer ID`.
  An initial sandboxed signature check failed; the same verification outside the
  sandbox succeeded. No signature/Gatekeeper bypass was used.
- Approved `open -a /Applications/Docker.app` succeeded. The bundled Docker CLI's
  `info` returned Engine **29.8.2**, and `compose version` returned **v5.5.1**.
  The working context is `desktop-linux`, using the user Docker Desktop socket.
  Docker socket access required approved execution outside the filesystem sandbox.

The first image build failed because `docker-credential-desktop` was not on
`PATH`. Re-running with the app's bundled binary directory on the command-local
`PATH` succeeded. This avoids requiring global links or privileged helper setup:

```sh
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker info
docker compose version
```

Docker Desktop remains running. The acceptance services were explicitly stopped
after successful verification; they are not claimed to be currently serving.
Their containers, images, named volumes, and synthetic data were retained.
Final daemon inspection reported architecture `aarch64`. The five service
containers and controlled worker were stopped; the frontend's exit 143 resulted
from the intentional SIGTERM stop, not a failed startup or health check.

### Isolated stack, builds, health, and migrations

Preflight found no existing Docker containers or volumes. An approved temporary
loopback bind check confirmed ports 5432, 8000, 5173, 3200, and 4318 were free.
No unrelated services were stopped. No `.env` existed, and none was created or
overwritten. The following credentials are deliberately synthetic acceptance
fixtures, not deployment secrets:

```sh
export POSTGRES_PASSWORD=m1-acceptance-only
export SENTINEL_API_TOKEN=m1-acceptance-only-token
dc() { docker compose -p sentinel-m1-macos-acceptance -f infra/compose.yaml "$@"; }
dc config --quiet
dc config --format json | backend/.venv/bin/python infra/check_bindings.py
dc build api worker frontend
dc pull postgres tempo
dc up -d --wait --wait-timeout 60 postgres
dc run --rm api alembic upgrade head
dc up -d --wait --wait-timeout 180
dc exec -T api alembic current
dc exec -T api alembic check
dc exec -T api python -m sentinel.worker.smoke
```

All commands above passed after the PATH correction. API, worker, and frontend
images built for the Apple Silicon Docker runtime; the locked dependencies were
installed by the image builds. PostgreSQL ran **16.15** from `postgres:16-alpine`;
Tempo ran the approved `grafana/tempo:2.9.0`. Migration revision was `0001 (head)`,
and `alembic check` reported no new upgrade operations.

`dc ps --all` and actual container inspection showed all five services healthy:

| Service | Observed health | Actual host binding / persistent storage |
| --- | --- | --- |
| PostgreSQL | healthy | `127.0.0.1:5432`; `sentinel-m1-macos-acceptance_postgres-data` |
| API | healthy | `127.0.0.1:8000`; no data volume |
| Worker | healthy | no published ports; no data volume |
| Frontend | healthy | `127.0.0.1:5173`; no data volume |
| Tempo | healthy | `127.0.0.1:3200`, `127.0.0.1:4318`; `sentinel-m1-macos-acceptance_tempo-data` |

Actual mounts placed PostgreSQL data at `/var/lib/postgresql/data` and Tempo data
at `/var/tempo`; Tempo's config mount was read-only. API/worker ran as `sentinel`,
frontend as `node`, and Tempo as `10001:10001`. The PostgreSQL image's configured
user was empty (its upstream entrypoint handles initialization/user switching);
this inspection alone does not claim every PostgreSQL process runs as root.

Actual HTTP checks returned 200 for API `/health/live`, `/health/ready`, frontend
`/`, and frontend `/health/ready` (the API proxy). Readiness reported PostgreSQL
and Tempo available. From the API container, PostgreSQL/Tempo DNS resolution and
Tempo `/ready` succeeded. Settings checks confirmed the required token was
nonempty, the database used `postgres:5432`, and queue settings were 60/15/3.
No environment values or resolved credentials were printed by these inspections.

Empty API token and empty PostgreSQL password each caused `dc config --quiet`
to fail interpolation with exit status 1, as required. Stopping only Tempo left
API readiness at HTTP 200 with exactly
`{"status":"ready","postgres":"available","tempo":"unavailable"}`.
Tempo was restarted; a final full-stack health wait and availability probe passed.

### Actual in-flight interruption, fencing, and persistence

The default probe is too fast to interrupt reproducibly. A disposable harness at
`/private/tmp/sentinel-m1-runtime.vEqESx/verify_runtime.py` used the existing
`Worker.handlers` registry and `PostgresJobStore.clock` injection point. It was
mounted read-only into a dedicated one-off worker container in the acceptance
project. Its SHA-256 is
`3702ca97e1d4c24764f72df9cae628a009a5b51bb0fb7a3301bac4a0e5e5cdcb`.
It is a local verification artifact, not committed application code or a CI test.

The harness ran with the acceptance environment above and:

```sh
SENTINEL_DATABASE_URL=postgresql+psycopg://sentinel:m1-acceptance-only@127.0.0.1:5432/sentinel \
  backend/.venv/bin/python /private/tmp/sentinel-m1-runtime.vEqESx/verify_runtime.py
```

It exited 0 and established the following, without outbound target HTTP requests:

1. With the normal worker stopped, it committed job
   `b0d79bc1-5e47-4ce2-b283-3b988fc6c0c8` / execution
   `159a3626-d729-4131-9006-b613fcc0096d`. API restart preserved its queued state;
   restarting the worker completed that same job at delivery count 1.
2. A controlled worker acquired job `d1e8a5ee-c199-41e1-a0e0-d77c7c7f8fbc` /
   execution `08da8a46-976d-408f-9594-54f8c0d58789`, with state `leased/running`
   and delivery count 1. Advancing the injected clock by 10 seconds and observing
   the real heartbeat confirmed the expiry became controlled time + 60 seconds,
   without changing the token. The harness's heartbeat interval was 0.2 seconds
   solely for operational synchronization; production remains 15 seconds.
3. `docker kill --signal KILL
   sentinel-m1-macos-acceptance-controlled-worker` terminated the in-flight
   container with exit code 137. Its original job remained `leased/running` at
   delivery count 1; no replacement job was created.
4. The harness advanced the clock beyond the persisted lease deadline. Both
   heartbeat and completion with the expired token raised `LeaseLost` even before
   reclaim. Restarting the **same container** reclaimed the original job with a
   new owner/token and delivery count 2. Both stale-token operations again raised
   `LeaseLost`, without changing the replacement ownership.
5. Releasing the handler gate completed the original job as `succeeded/completed`
   at count 2. The controlled container exited 0. Its restart policy was `no`, so
   reclaim was caused by the explicit restart, not an unobserved automatic loop.
6. A separate infrastructure-retry probe,
   `7d45ada0-1926-4613-92f5-4f1ddd6bd3d0`, obeyed 5/30-second backoff and was not
   claimable before either deadline. Its third failed delivery atomically became
   `dead/failed`, with verdict `not_evaluated`; no fourth claim was possible.
7. Snapshots of those three original job/execution pairs survived both
   `dc restart postgres` and
   `dc up -d --force-recreate --wait --wait-timeout 45 postgres`.
   The replacement container ID changed; its mounted named volume stayed
   `sentinel-m1-macos-acceptance_postgres-data`. All snapshots matched afterward.

Lease deadlines/backoff were advanced through the injected clock, not sleeps or
direct queue-row mutations. Bounded polling synchronized process startup,
heartbeat commits, and handler completion; it did not simulate lease expiration.
The normal worker was restored afterward. The final newly inserted smoke probe
verified availability only; it was not used as evidence of in-flight recovery.

### Fresh automated checks

A new dedicated `sentinel_acceptance_test` database was created inside acceptance
PostgreSQL. Integration fixtures and downgrade touched only that disposable test
database; application acceptance records survived.

```sh
dc exec -T postgres createdb -U sentinel sentinel_acceptance_test
export SENTINEL_DATABASE_URL=postgresql+psycopg://sentinel:m1-acceptance-only@127.0.0.1:5432/sentinel_acceptance_test
export SENTINEL_TEST_DATABASE_URL="$SENTINEL_DATABASE_URL"
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
# The full-suite commands ran from backend/, with both URL variables inherited:
(cd backend && .venv/bin/pytest tests -q)
backend/.venv/bin/alembic -c backend/alembic.ini downgrade base
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
backend/.venv/bin/alembic -c backend/alembic.ini check
(cd backend && .venv/bin/pytest tests -q)
backend/.venv/bin/ruff check backend
backend/.venv/bin/ruff format --check backend
# Working directory: backend/
.venv/bin/mypy
```

Both full suites actually ran against containerized PostgreSQL: **44 passed in
0.80 seconds** each (23 integration, 21 unit/contract). Coverage includes real
concurrent claims, lease expiry/recovery, heartbeat behavior, stale fencing,
exhaustion, invalid transitions, and transaction rollback. The second suite ran
after PostgreSQL replacement and test-schema downgrade/re-upgrade. Migration
commands passed, and drift was absent. Ruff passed with 35 formatted files; mypy
passed over 33 source files. One lint invocation used the wrong relative path
from `backend/` and exited 127; the corrected commands above passed.

From `frontend/`, and again via `dc exec -T frontend sh -c '...'`, every command
below passed:

```sh
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
```

Vitest ran **1 passing test** in each environment; Vite built 29 modules.
OpenAPI export plus `npm run api:generate` produced identical pre/post SHA-256
hashes for both committed-contract artifacts. Git diff alone was not used to
claim drift detection because this checkout's files are still untracked.

### CI review and remaining gate

`.github/workflows/ci.yaml` parsed successfully. Its backend, frontend, and Compose
jobs, read-only repository permission, real PostgreSQL service, migration
ordering, dependency locks, frontend checks, smoke probe, and Tempo-outage
assertion match the corresponding checks executed locally. Cleanup does not
delete named volumes. This is static review and local command evidence, **not a
GitHub Actions run** or an actionlint result; actionlint is unavailable.

`git remote -v` returned no remotes, and `git rev-parse --verify HEAD` failed
because there is no commit. `gh` is unavailable. There is no remote run/commit
to inspect or match to this implementation. No credentials were enumerated, and
no commit, push, remote creation, or remote workflow trigger was performed.

The existing workflow still does not enforce the controlled in-flight
interruption/fencing and original-record persistence scenarios. Those have now
passed locally; the disposable harness is not automatically reproducible in CI
and is not retained by Git. Moving it into a reviewed repeatable acceptance test
is a remaining test-maintenance limitation, not a claim that the present workflow
has that coverage. Apple Silicon success also does not verify the Ubuntu/x86-64
Actions environment.

| Mandatory check | Current actual status |
| --- | --- |
| Docker installation/start and CLI/Compose | Verified; bundled PATH works, global links incomplete |
| API/worker/frontend image builds | Passed |
| Complete Compose startup and five health checks | Passed; intentionally stopped afterward |
| Containerized PostgreSQL migrations | Passed: `0001`, no drift; disposable rollback/re-upgrade passed |
| Durable claims, heartbeat, fencing, retry exhaustion | Passed: PostgreSQL suite plus runtime fault injection |
| Actual in-flight worker crash/restart recovery | Passed: same job, new token, count 1 -> 2 |
| PostgreSQL restart/replacement persistence | Passed: original records and same named volume |
| Loopback bindings, environment, networking, Tempo outage | Passed with actual runtime checks |
| Backend/frontend automated checks | Passed locally, including Docker-hosted PostgreSQL and container frontend |
| GitHub Actions execution for this implementation | Unverified; no remote/commit; mandatory roadmap gate remains open |

Final cleanup used `dc stop`, not `down --volumes`, volume pruning, or data reset.
Both acceptance named volumes remain. The controlled one-off worker is also
retained stopped; Compose reports it as an orphan, which is expected for this
temporary override. Do not use a broad orphan/volume cleanup command to hide it.
The temporary harness directory remains available for inspection, but it is not
a substitute for a tracked automated acceptance test. No user data was deleted.

**Readiness:** the local Docker runtime gate is satisfied and the foundation is
technically ready for Milestone 2. Milestone 1 is not formally accepted and
Milestone 2 must not start until an authorized repository/commit and a passing
GitHub Actions run satisfy the unchanged roadmap gate. No Milestone 2 code was
implemented.

## Migration pre-commit audit: 2026-10-09

The implementation was migrated from the original checkout into the cloned
`amnotwallas/sentinel` repository. All 79 commit-candidate files initially matched
the original byte for byte. The target branch is `main`, tracking `origin/main`;
the remote's README bootstrap commit is `313f77b`. No implementation commit or
push is authorized yet.

The pre-commit review expanded Git and Docker exclusions for local environments,
secret material, caches, build/test output, editor state, and runtime/database
artifacts. Dependency locks and the OpenAPI/generated client remain intentional
versioned inputs to CI. Current status notes were updated for the new remote;
historical evidence above remains labeled as such. Personal home-directory paths
in the earlier runtime inventory were made portable.
Extra blank lines at EOF were removed where Git's staged whitespace check
reported them; accepted ADR content and decisions were unchanged.

Fresh checks in the migrated checkout passed:

- Backend: Ruff lint and format, strict mypy, 21 unit/contract tests, 23 focused
  PostgreSQL integration tests, and the full 44-test backend suite.
- Migrations: upgrade, downgrade in a disposable test database, re-upgrade,
  `alembic check`, revision `0001 (head)`, and reviewed offline SQL generation.
- Frontend: ESLint, Prettier, strict TypeScript, one Vitest component test, build,
  identical SHA-256 hashes after OpenAPI/client regeneration, and an npm audit
  reporting zero vulnerabilities.
- Compose: rendered default loopback bindings, API/worker/frontend image builds,
  five healthy services, live/readiness/frontend proxy checks, durable worker
  probe, and readiness remaining HTTP 200 while Tempo was stopped.
- Hygiene: candidate-file credential patterns and credential assignments reviewed;
  only synthetic local/CI values and test canaries were found. No real credential
  was detected. Documentation relative links and CI/Compose structure passed.

The first full-suite attempt inherited the validation stack's bearer token and
returned 401 instead of the unauthenticated contract test's expected 404. A
single-test comparison reproduced the failure only with that environment value.
Removing the Compose-only token from the native test environment made the full
suite pass; repository test and production code were unchanged.

Validation used an isolated Compose project and a new PostgreSQL test database.
Only that audit project's containers, network, and disposable volumes were
removed afterward; the original acceptance resources were preserved.

The mandatory GitHub Actions gate remains unverified until an authorized
implementation commit and push. The earlier controlled crash/persistence harness
is still temporary rather than tracked CI coverage. These limitations remain;
Milestone 1 is not formally accepted and Milestone 2 has not started.

## Post-push acceptance update: 2026-10-09

The explicitly authorized commit and push completed as
`62635ea71566dc8e21118667a393ed944f6a0cce` on `main` in `amnotwallas/sentinel`.
The user subsequently confirmed the backend, frontend (Vitest 1/1), and Compose
Actions jobs passed and explicitly identified Milestone 1 as complete. This
supersedes the earlier pending-CI/authorization status above; no acceptance
criterion was removed. Remote workflow URL/logs remain uncaptured in this ledger.

The process-level crash/persistence harness remains temporary rather than tracked
CI coverage. Retaining it as repeatable automation is a developer-workflow
recommendation, not an assertion that it already runs in GitHub Actions. This
workflow audit added no Milestone 2 product code or additional commits/pushes.

## File inventory

The original `AGENTS.md`, MVP, and accepted ADRs are preserved. Architecture and
roadmap files gained links/status notes for the implemented foundation.

- Root: `.gitignore`, `.dockerignore`, `.env.example`, `README.md`.
- Backend tooling: `backend/pyproject.toml`, `backend/uv.lock`,
  `backend/Dockerfile`, `backend/alembic.ini`.
- Migrations: `backend/migrations/env.py`, `backend/migrations/script.py.mako`,
  `backend/migrations/versions/0001_durable_work.py`.
- Shared configuration: `backend/src/sentinel/config.py` and package initializers
  for the approved module directories.
- Execution: `execution/domain.py`, `execution/ports.py`, `execution/service.py`.
- Persistence: `persistence/database.py`, `persistence/models.py`,
  `persistence/queue.py`.
- API: `api/app.py`, `api/main.py`, `api/problems.py`, `api/export.py`.
- Worker: `worker/runtime.py`, `worker/main.py`, `worker/health.py`,
  `worker/probe.py`, `worker/smoke.py`.
- Telemetry: `telemetry/runtime.py`.
- Backend tests: `backend/tests/conftest.py`, `tests/__init__.py`,
  `unit/test_jobs.py`, `unit/test_settings.py`, `integration/test_queue.py`,
  `integration/test_worker.py`, `contract/test_health.py`.
- Frontend tooling: `frontend/package.json`, `frontend/package-lock.json`,
  `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/eslint.config.js`,
  `frontend/.prettierrc.json`, `frontend/.prettierignore`, `frontend/Dockerfile`,
  `frontend/index.html`.
- Frontend shell/client: `frontend/src/App.tsx`, `src/main.tsx`, `src/styles.css`,
  `src/features/README.md`, `src/shared/api/client.ts`,
  `src/shared/api/generated/schema.ts`, `frontend/openapi.json`.
- Frontend tests: `frontend/tests/setup.ts`, `frontend/tests/App.test.tsx`.
- Infrastructure: `infra/compose.yaml`, `infra/tempo/tempo.yaml`,
  `infra/check_bindings.py`.
- CI: `.github/workflows/ci.yaml`.
- Documentation: this ledger, `docs/operations/durable-work.md`,
  `docs/ROADMAP.md`, `docs/architecture/README.md`.
