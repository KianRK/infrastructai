.DEFAULT_GOAL := help
PY_PROJECTS := training serving
# PyTorch build for training: gpu (CUDA 13.0 wheels) or cpu.
TORCH ?= gpu
# `uv run` must not re-sync, or it would remove the selected PyTorch extra.
export UV_NO_SYNC := 1

.PHONY: help install lint format typecheck test check data-download data-prepare train mlflow-ui serve-local

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

serve-local: ## Run the Ray Serve app with dummy models at http://localhost:8000/api/docs
	cd serving && uv run serve run config/serve.local.yaml
