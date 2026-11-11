.DEFAULT_GOAL := help
PY_PROJECTS := training serving

.PHONY: help install lint format typecheck test check

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Install all Python and frontend dependencies
	@for p in $(PY_PROJECTS); do (cd $$p && uv sync) || exit 1; done
	cd frontend && npm ci

lint: ## Lint Python (ruff) and frontend (ESLint)
	@for p in $(PY_PROJECTS); do (cd $$p && uv run ruff check . && uv run ruff format --check .) || exit 1; done
	cd frontend && npm run lint

format: ## Auto-format and auto-fix Python
	@for p in $(PY_PROJECTS); do (cd $$p && uv run ruff check --fix . && uv run ruff format .) || exit 1; done

typecheck: ## Type-check Python (mypy) and frontend (tsc)
	@for p in $(PY_PROJECTS); do (cd $$p && uv run mypy) || exit 1; done
	cd frontend && npm run typecheck

test: ## Run all tests
	@for p in $(PY_PROJECTS); do (cd $$p && uv run pytest) || exit 1; done
	cd frontend && npm test

check: lint typecheck test ## Everything CI runs
