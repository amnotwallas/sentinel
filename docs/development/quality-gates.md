# Local quality gates

Run from the worktree root. Install locked dependencies with `make setup`.
These wrappers reuse existing tools and do not replace the three CI jobs.
`make check-fast` is local feedback, not milestone acceptance.

| Gate | Command | When |
| --- | --- | --- |
| Backend lint/format/strict types + non-integration tests | `make check-backend` | Backend edits and handoff |
| Frontend lint/format/strict types + Vitest + build | `make check-frontend` | Frontend edits and handoff |
| OpenAPI and TypeScript byte-for-byte drift, temporary outputs | `make check-contract` | API/client changes and integration |
| Planned M2 schema/examples and temporary TypeScript compilation | `make check-planned-contract` | Contract planning/handoff |
| Developer checker lint/format/strict types | `make check-tooling` | Checker changes |
| All preceding local gates | `make check-fast` | Integrated local candidate |
| Rendered Compose configuration and loopback ports | `make check-compose-config` | Infrastructure or milestone gate |
| Real PostgreSQL/full pytest/migrations | Recipe below | Persistence, concurrency, migration and milestone changes |
| Full Compose startup, probe and outage readiness | Recipe below | Runtime/infrastructure and milestone acceptance |

For the TDD loop, run the smallest useful behavior test first, verify the expected
failure, implement, then run that test and the relevant final gates. Examples:

```sh
env -u SENTINEL_API_TOKEN -u SENTINEL_API_HOST uv run --frozen --project backend pytest backend/tests/unit/test_jobs.py
npm --prefix frontend test -- tests/App.test.tsx
```

The backend wrapper removes the runtime token and bind-host variables only for
the non-integration test command. Other operator `SENTINEL_*` settings can still
affect tests: use a clean development shell, and explicitly inject test settings.
Do not print the environment to diagnose contamination. The contract checker
removes all `SENTINEL_*` variables from its subprocesses and writes only temporary
generation outputs. It compares the worktree's candidate artifacts, including
uncommitted changes, without normalizing away accidental edits.

## Contract handoff

`make check-planned-contract` validates local-only schema references, the 16
planned catalog operations, positive/negative structural examples and generated
TypeScript examples in a temporary directory. It uses the existing locked
Redocly/AJV dependency, adds no package, and leaves runtime artifacts unchanged.
It meta-validates every component, including unused future models, and rejects
unplanned operations, including TRACE. The installed TypeScript generator needs
`defaultNonNullable: false` to preserve optional inputs and explicit discriminator
mappings to preserve wire tags. Its recursive indexed array types trigger TS2502;
the checker uses the public `postTransform` API to derive named recursive aliases
from the generated AST and rejects any generated `any`. No wire shape is handwritten.
When these definitions enter the active API, the coordinator must apply the same
generation options/transform to the active generator and its drift check in that
slice. The current health-only generator and existing CI remain unchanged.
It does not prove service transactions, secret-literal policy, decimal fidelity,
UTF-8 byte limits, or runtime Pydantic conformance; each slice adds those tests.
The planned contracts include future execution/import components without routes;
imports are outside current MVP/M2 and need a product/ADR decision before implementation.

Only the assigned generated-contract owner updates committed artifacts:

```sh
env -u SENTINEL_API_TOKEN -u SENTINEL_API_HOST uv run --frozen --project backend python -m sentinel.api.export frontend/openapi.json
npm --prefix frontend run api:generate
make check-contract
```

Use a clean shell for regeneration as well. Review both artifact diffs and run
frontend typecheck/tests. The backend's Pydantic schemas are authoritative;
handwritten TypeScript shapes or edits to generated types are not a workaround.
Keep examples synthetic and verify response headers and problem schemas in API
contract tests. Do not regenerate in two worktrees while integrating one API slice.

## Isolated PostgreSQL and Docker recipe

Use a freshly created disposable Compose project, a dedicated `_test` database,
and reserved loopback ports. This example requires Compose supporting `!override`
(2.24.4+; see [Docker's override rules](https://docs.docker.com/reference/compose-file/merge/#replace-value);
the installed version at audit was 5.5.1). Existing startup instructions
remain valid for the default stack; this override is only for validation.
Change project/database/ports for each simultaneous writer and record them in the
task packet. Use a dedicated validation shell so these synthetic exports cannot
overwrite settings in a running development session. Inspect `docker compose ls`
and `docker ps --format '{{.Names}} {{.Ports}}'`; on macOS, also inspect
`lsof -nP -iTCP:55432 -iTCP:58000 -iTCP:55173 -iTCP:53200 -iTCP:54318 -sTCP:LISTEN`.
If a project or port is occupied, choose different values rather than stopping it.
The commands below never reuse the ordinary `sentinel` project.

```sh
sentinel_check_project=sentinel-check-$(openssl rand -hex 6)
docker compose ls --all
docker ps -a --filter "label=com.docker.compose.project=$sentinel_check_project" --format '{{.Names}}'
docker volume ls --filter "label=com.docker.compose.project=$sentinel_check_project" --format '{{.Name}}'
sentinel_check_override=$(mktemp /private/tmp/sentinel-check.XXXXXX)
cat > "$sentinel_check_override" <<'YAML'
services:
  postgres:
    ports: !override ["127.0.0.1:55432:5432"]
  api:
    ports: !override ["127.0.0.1:58000:8000"]
  frontend:
    ports: !override ["127.0.0.1:55173:5173"]
  tempo:
    ports: !override ["127.0.0.1:53200:3200", "127.0.0.1:54318:4318"]
YAML
export POSTGRES_USER=sentinel POSTGRES_DB=sentinel_m2_backend_test
export POSTGRES_PASSWORD=disposable-check-only SENTINEL_API_TOKEN=disposable-check-only-token
export SENTINEL_TEST_DATABASE_URL=postgresql+psycopg://sentinel:disposable-check-only@127.0.0.1:55432/sentinel_m2_backend_test
export SENTINEL_DATABASE_URL="$SENTINEL_TEST_DATABASE_URL"
docker compose --env-file /dev/null -p "$sentinel_check_project" -f infra/compose.yaml -f "$sentinel_check_override" config --quiet
docker compose --env-file /dev/null -p "$sentinel_check_project" -f infra/compose.yaml -f "$sentinel_check_override" config --format json | uv run --frozen --project backend python infra/check_bindings.py
docker compose --env-file /dev/null -p "$sentinel_check_project" -f infra/compose.yaml -f "$sentinel_check_override" up -d --wait postgres
uv run --frozen --project backend alembic -c backend/alembic.ini upgrade head
uv run --frozen --project backend alembic -c backend/alembic.ini check
env -u SENTINEL_API_TOKEN -u SENTINEL_API_HOST uv run --frozen --project backend pytest backend/tests
uv run --frozen --project backend alembic -c backend/alembic.ini upgrade head --sql
```

The project-filtered container and volume inventories must be empty before the
first startup; regenerate the random project name if they are not. Random names
also prevent silently reusing volumes from a previous validation run.

Do not run this suite concurrently in the same database: fixtures delete rows.
The suffix check in `conftest.py` is a guard, not proof a database is disposable.
Only in the **new database created above**, review downgrade SQL/data loss and run:

```sh
uv run --frozen --project backend alembic -c backend/alembic.ini downgrade head:base --sql
uv run --frozen --project backend alembic -c backend/alembic.ini downgrade base
uv run --frozen --project backend alembic -c backend/alembic.ini upgrade head
uv run --frozen --project backend alembic -c backend/alembic.ini check
uv run --frozen --project backend alembic -c backend/alembic.ini current
```

The full-stack gate can reuse this task-owned disposable project after native
tests finish. Reserve all five ports; only one agent owns this runtime. On this
macOS installation Docker builds may require the Docker Desktop credential-helper
directory on command-local `PATH`: `/Applications/Docker.app/Contents/Resources/bin`.

```sh
docker compose --env-file /dev/null -p "$sentinel_check_project" -f infra/compose.yaml -f "$sentinel_check_override" run --build --rm api alembic upgrade head
docker compose --env-file /dev/null -p "$sentinel_check_project" -f infra/compose.yaml -f "$sentinel_check_override" up -d --build --wait --wait-timeout 180
docker compose --env-file /dev/null -p "$sentinel_check_project" -f infra/compose.yaml -f "$sentinel_check_override" exec -T api python -m sentinel.worker.smoke
curl --fail http://127.0.0.1:55173/health/live
docker compose --env-file /dev/null -p "$sentinel_check_project" -f infra/compose.yaml -f "$sentinel_check_override" stop tempo
uv run --frozen --project backend python -c "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:58000/health/ready', timeout=5)); assert r['status']=='ready' and r['tempo']=='unavailable'"
```

Capture task-owned diagnostic logs when checks fail, review them for sensitive
content before including evidence, and report failures. Cleanup applies **only**
to the disposable project created by this task, after preserving needed evidence:

```sh
docker compose --env-file /dev/null -p "$sentinel_check_project" -f infra/compose.yaml -f "$sentinel_check_override" down --volumes
unset SENTINEL_DATABASE_URL SENTINEL_TEST_DATABASE_URL SENTINEL_API_TOKEN
unset POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD
```

Never use this volume deletion on an existing project, user database or another
agent's resources. Do not use global prune or `--remove-orphans` to hide unrelated
containers. Remove only the temporary override file when it is no longer needed.
Container isolation avoids the shared native worker health-marker path.

## Evidence and CI

Record candidate/base identity, commands, exit results, counts, environment
isolation, migration head/SQL and skipped gates with reasons. Relevant checks must
pass on the integrated candidate, not only on an earlier dependency branch.
Changing candidate files after verification invalidates the affected evidence.

The existing `checks` workflow already runs backend PostgreSQL tests and migration
round trips, frontend contract drift and quality checks, and Compose probe/outage
acceptance. After an authorized push, verify all three job results against the
exact pushed SHA and include the run URL. Local passing results do not establish
remote CI status. Do not retry a deterministic failure repeatedly without first
investigating its cause.
