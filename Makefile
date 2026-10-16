.PHONY: setup check-fast check-backend check-frontend check-contract check-planned-contract check-tooling check-compose-config

setup:
	uv sync --project backend --frozen
	npm --prefix frontend ci

# Quick feedback only. PostgreSQL/migration and full Docker gates are separate.
check-fast: check-backend check-frontend check-contract check-planned-contract check-tooling

check-backend:
	uv run --frozen --project backend ruff check backend
	uv run --frozen --project backend ruff format --check backend
	cd backend && uv run --frozen mypy
	env -u SENTINEL_API_TOKEN -u SENTINEL_API_HOST uv run --frozen --project backend pytest backend/tests -m 'not integration'

check-frontend:
	npm --prefix frontend run lint
	npm --prefix frontend run format:check
	npm --prefix frontend run typecheck
	npm --prefix frontend test
	npm --prefix frontend run build

check-contract:
	uv run --frozen --project backend python infra/check_contract.py

check-planned-contract:
	node infra/check_planned_contracts.mjs

check-tooling:
	uv run --frozen --project backend ruff check --config backend/pyproject.toml infra/check_contract.py
	uv run --frozen --project backend ruff format --check --config backend/pyproject.toml infra/check_contract.py
	uv run --frozen --project backend mypy --strict --config-file backend/pyproject.toml infra/check_contract.py
	node --check infra/check_planned_contracts.mjs
	node --check frontend/scripts/generate-api.mjs
	node frontend/node_modules/.bin/prettier --config frontend/.prettierrc.json --check infra/check_planned_contracts.mjs docs/contracts/milestone-2.openapi.json docs/contracts/milestone-2.fixtures.json

check-compose-config:
	POSTGRES_PASSWORD=validation-only SENTINEL_API_TOKEN=validation-only-token docker compose -f infra/compose.yaml config --quiet
	POSTGRES_PASSWORD=validation-only SENTINEL_API_TOKEN=validation-only-token docker compose -f infra/compose.yaml config --format json | uv run --frozen --project backend python infra/check_bindings.py
