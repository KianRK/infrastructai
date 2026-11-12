.DEFAULT_GOAL := help
SHELL := /bin/bash
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
# Terraform binary (1.17 or newer).
TERRAFORM ?= terraform
# Image tag for the cluster: the commit, so every deployment is traceable.
TAG ?= $(shell git rev-parse --short=12 HEAD)
CHART := deploy/helm/roadscan
# Hours until a demo started with `make demo-up` is stopped automatically.
HOURS ?= 2

.PHONY: help install lint format typecheck test check data-download data-prepare train mlflow-ui serve-local serve-models frontend-dev docker-build compose-up compose-up-models compose-down model-fetch smoke-test infra-check infra-plan infra-apply chart-check platform-install deploy-local aks-credentials images-push deploy demo-up demo-down demo-status github-setup

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-17s %s\n", $$1, $$2}'

install: ## Install all Python and frontend dependencies
	cd training && uv sync --extra $(TORCH)
	cd serving && uv sync
	cd frontend && npm ci

lint: ## Lint Python (ruff) and frontend (ESLint)
	@for p in $(PY_PROJECTS); do (cd $$p && uv run ruff check . && uv run ruff format --check .) || exit 1; done
	cd serving && uv run ruff check ../scripts && uv run ruff format --check ../scripts
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
	@curl -sf -m 3 -o /dev/null http://127.0.0.1:5000/health || { \
		echo "The MLflow server is not running; the detector is loaded from its registry."; \
		echo "Start it in another terminal first: make mlflow-ui"; exit 1; }
	cd serving && MLFLOW_TRACKING_URI=http://127.0.0.1:5000 uv run serve run config/serve.models.yaml

frontend-dev: ## Run the frontend at http://localhost:5173 (needs serve-local or serve-models)
	cd frontend && npm run dev

docker-build: ## Build the three images (training, serving, frontend)
	docker build -t roadscan-training:local training
	docker build -t roadscan-serving:local-models serving
	docker build -t roadscan-frontend:local frontend

compose-up: ## Run frontend + backend in containers with dummy models at http://localhost:8080
	docker compose up --build --detach --wait
	@echo "Open http://localhost:8080 (password: $(ROADSCAN_DEMO_PASSWORD)). Stop with: make compose-down"

model-fetch: ## Copy the registered "production" detector to ./models (for compose-up-models)
	rm -rf models/roadscan-detector
	cd training && MLFLOW_TRACKING_URI=sqlite:///mlflow.db uv run mlflow artifacts download \
		--artifact-uri "models:/roadscan-detector@production" --dst-path ../models/roadscan-detector
	chmod -R a+rX models/roadscan-detector

compose-up-models: ## Same with the real detector and LLM (needs `make model-fetch` once)
	@test -f models/roadscan-detector/model.onnx || { echo "Run first: make model-fetch"; exit 1; }
	docker compose -f compose.yaml -f compose.models.yaml up --build --detach --wait
	@echo "Open http://localhost:8080 (password: $(ROADSCAN_DEMO_PASSWORD)). Stop with: make compose-down"

compose-down: ## Stop the containers
	docker compose down

smoke-test: ## Check a running stack end to end (URL=http://localhost:8080)
	python3 scripts/smoke_test.py $(or $(URL),http://localhost:8080)

infra-check: ## Format-check and validate the Terraform configuration (no Azure login needed)
	$(TERRAFORM) -chdir=infra fmt -check -recursive
	$(TERRAFORM) -chdir=infra init -backend=false -input=false
	$(TERRAFORM) -chdir=infra validate

infra-plan: ## Plan the Azure infrastructure (needs `az login` and infra/terraform.tfvars)
	$(TERRAFORM) -chdir=infra init -input=false
	$(TERRAFORM) -chdir=infra plan -out tfplan

infra-apply: ## Apply the plan made by infra-plan (creates billable resources)
	$(TERRAFORM) -chdir=infra apply tfplan

chart-check: ## Lint the Helm chart and render it with the local and the AKS example values
	helm lint $(CHART) -f $(CHART)/values-local.yaml
	helm lint $(CHART) -f $(CHART)/values-aks.example.yaml
	helm template roadscan $(CHART) -f $(CHART)/values-local.yaml > /dev/null
	helm template roadscan $(CHART) -f $(CHART)/values-aks.example.yaml > /dev/null

platform-install: ## Install Envoy Gateway, cert-manager and KubeRay into the current cluster (admin, once)
	deploy/platform/install.sh

deploy-local: ## Deploy to a local cluster (minikube/kind) with dummy models; see deploy/README.md
	kubectl -n roadscan create secret generic roadscan-secrets --dry-run=client -o yaml \
		--from-literal=demo-password=$(ROADSCAN_DEMO_PASSWORD) \
		--from-literal=jwt-secret=$(ROADSCAN_JWT_SECRET) | kubectl apply -f -
	scripts/deploy.sh -f $(CHART)/values-local.yaml

aks-credentials: ## Point kubectl at the AKS cluster created by Terraform (needs kubelogin)
	az aks get-credentials --overwrite-existing \
		--resource-group "$$($(TERRAFORM) -chdir=infra output -raw resource_group)" \
		--name "$$($(TERRAFORM) -chdir=infra output -raw aks_name)"
	kubelogin convert-kubeconfig -l azurecli

images-push: ## Build the serving and frontend images and push them to the Azure registry (TAG=commit)
	scripts/push_images.sh "$$($(TERRAFORM) -chdir=infra output -raw acr_login_server)" $(TAG)

deploy: ## Deploy the pushed images to AKS with values from the Terraform outputs (TAG=commit)
	set -o pipefail; $(TERRAFORM) -chdir=infra output -json | python3 scripts/aks_values.py \
		| scripts/deploy.sh -f - --set image.tag=$(TAG)

demo-up: ## Start the demo cluster, deploy the newest pushed image, smoke test (HOURS=2 until auto-stop)
	scripts/demo.sh up $(HOURS)
	$(MAKE) aks-credentials
	$(MAKE) deploy TAG="$$(scripts/demo.sh latest-tag "$$($(TERRAFORM) -chdir=infra output -raw acr_login_server)")"
	ROADSCAN_DEMO_PASSWORD="$$($(TERRAFORM) -chdir=infra output -raw demo_password_command | sh)" \
		python3 scripts/smoke_test.py "https://$$($(TERRAFORM) -chdir=infra output -raw hostname)"
	@echo "Demo: https://$$($(TERRAFORM) -chdir=infra output -raw hostname)"

demo-down: ## Stop the demo cluster (no compute cost while stopped)
	scripts/demo.sh down

demo-status: ## Show whether the demo cluster runs and when it stops
	scripts/demo.sh status

github-setup: ## Write the repository secrets for the CD and Demo workflows from the Terraform outputs
	scripts/github_setup.sh
