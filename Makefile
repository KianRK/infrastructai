.DEFAULT_GOAL := help
PY_PROJECTS := training serving
# PyTorch build for training: gpu (CUDA 13.0 wheels) or cpu.
TORCH ?= gpu
# `uv run` must not re-sync, or it would remove the selected PyTorch extra.
export UV_NO_SYNC := 1
# Ray workers inherit the interpreter instead of being re-launched through `uv run`.
export RAY_ENABLE_UV_RUN_RUNTIME_ENV := 0
# Development-only credentials for the local serve targets. The deployed application
# reads its secrets from Azure Key Vault instead.
export ROADSCAN_DEMO_PASSWORD ?= roadscan-dev
export ROADSCAN_JWT_SECRET ?= local-development-signing-key-not-for-production

.PHONY: help install lint format typecheck test check data-download data-prepare train mlflow-ui serve-local serve-models frontend-dev

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Install all Python and frontend dependencies
	cd training && uv sync --extra $(TORCH)
	cd serving && uv sync
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

data-download: ## Download the configured RDD2022 countries (resumable; ~13 GB for all)
	cd training && uv run python -m rdd.download

data-prepare: ## Convert VOC annotations to YOLO format and create the train/val/test split
	cd training && uv run python -m rdd.prepare

train: ## Train, evaluate, export, and register the detector (config: training/configs/train.yaml)
	cd training && uv run python -m rdd.pipeline

mlflow-ui: ## Browse local experiments and the model registry at http://localhost:5000
	cd training && uv run mlflow ui --backend-store-uri sqlite:///mlflow.db

serve-local: ## Run the Serve app with dummy models on :8000 (password: roadscan-dev)
	cd serving && uv run serve run config/serve.local.yaml

serve-models: ## Run the Serve app with the registered detector and the real LLM (needs `make mlflow-ui`)
	cd serving && MLFLOW_TRACKING_URI=http://127.0.0.1:5000 uv run serve run config/serve.models.yaml

frontend-dev: ## Run the frontend at http://localhost:5173 (needs serve-local or serve-models)
	cd frontend && npm run dev
