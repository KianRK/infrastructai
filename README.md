# RoadScan

End-to-end road damage analysis: upload a road photo, an object detector trained on
RDD2022 localises the damage, and a small self-hosted LLM describes it. Served with
Ray Serve on Azure Kubernetes Service.

> **Status: work in progress.** Milestone 8 of 12 (authentication, rate limiting, upload validation). The full
> README (architecture, deployment, cost, model card) is written in the final milestone.

## Repository layout

| Path | Contents |
|---|---|
| `training/` | RDD2022 data pipeline and detector training (Python package `rdd`) |
| `serving/` | Ray Serve application: API, detector, LLM (Python package `app`) |
| `frontend/` | React + TypeScript + Vite web interface |
| `.github/workflows/` | CI (lint, type-check, tests, build) |

## Development

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js 24, GNU Make.

```bash
make install   # uv sync for both Python projects (TORCH=cpu for CPU-only PyTorch), npm ci
make check     # lint + type-check + tests, the same steps CI runs
make help      # all targets
```

Optional: `uvx pre-commit install` to run ruff on every commit.

## Data pipeline

The dataset is never committed; it is downloaded to `training/data/` (git-ignored).

```bash
make data-download   # fetches the countries listed in training/configs/data.yaml
make data-prepare    # VOC XML -> YOLO labels, stratified 80/10/10 split, dataset.yaml, stats.json
```

- **Download:** RDD2022 is one 13 GB zip on figshare containing one zip per country. The
  downloader fetches only the configured countries using HTTP range requests, resumes
  interrupted transfers, and verifies each archive's CRC-32. To iterate quickly, reduce
  `countries` in the config (e.g. `China_Drone` is 160 MB).
- **Conversion:** keeps the classes D00, D10, D20, D40 and drops all other labels; boxes are
  clipped to the image and empty boxes removed. Images without damage are kept as background.
- **Split:** RDD2022 publishes labels for its train split only, so that split is divided
  80/10/10 per country with a fixed seed. Images larger than 1280 px are downscaled.

## Training

```bash
make train       # train -> evaluate on the test split -> ONNX export -> quality gate -> register
make mlflow-ui   # inspect runs and the model registry
```

All hyperparameters live in `training/configs/train.yaml` (YOLO26s, 640 px, batch 16, mixed
precision; about 5 GB VRAM). Each pipeline execution is one MLflow run with the full config as
parameters, per-epoch training metrics, test-split mAP@0.5, mAP@0.5:0.95 and per-class metrics.

- **Quality gate:** the ONNX model is registered as `roadscan-detector` and given the alias
  `production` only if the configured test metric reaches the threshold. Otherwise the command
  exits with status 2 and nothing is registered.
- **Export:** ONNX with embedded NMS, so the serving image needs only ONNX Runtime.
- **Tracking server:** a local SQLite-backed MLflow store by default. Setting
  `MLFLOW_TRACKING_URI` to an Azure ML workspace switches tracking and registry there
  (`uv sync --extra gpu --extra azure`). To register an already trained checkpoint against
  another server without retraining:
  `uv run python -m rdd.pipeline --weights runs/<run>/weights/best.pt`

## Serving

```bash
make serve-local   # dummy detector and LLM, no weights needed
curl -F file=@road.jpg http://localhost:8000/api/analyze
```

One Ray Serve application with three deployments, composed through deployment handles:
`Api` (FastAPI ingress) -> `Detector` -> `Describer` (LLM). Backends are selected in the Serve
config file (`serving/config/serve.*.yaml`), which also sets replicas and CPU per deployment.
To run the real models locally, keep `make mlflow-ui` running in one terminal (it serves the
model registry) and start `make serve-models` in another. The LLM (1.1 GB) is downloaded on
first start.

- **Detector:** the ONNX model with the registry alias `production`, run with ONNX Runtime
  on CPU. Pre- and postprocessing (letterbox, mapping boxes back to the photo) is plain
  NumPy; neither PyTorch nor Ultralytics is installed in the serving environment.
- **LLM:** Qwen2.5-1.5B-Instruct (Apache-2.0), 4-bit GGUF via llama.cpp on CPU; vLLM on a
  GPU node is selectable with `llm.backend: vllm`.
- **Grounding:** the LLM never sees the image. It gets an aggregated summary of the
  detections (count, confidence, share of the image, position, a heuristic severity) and the
  curated reference notes (`serving/src/app/knowledge.yaml`) of the detected classes only.
  Its answer is checked: if it names a damage class that was not detected, or fails, a
  deterministic template text is returned instead (`description_source: "template"`); a
  detected class it leaves out is appended from the reference notes. With no detections the
  LLM is not called at all.

The response schema is defined with Pydantic (`serving/src/app/schemas.py`) and committed as
JSON Schema in `serving/contract/`; a contract test fails when the two diverge.

## Frontend

```bash
make serve-local    # terminal 1: backend with dummy models
make frontend-dev   # terminal 2: http://localhost:5173, password "roadscan-dev"
```

React + TypeScript + Vite. Login screen, image upload with client-side validation (JPEG, PNG,
WebP; 10 MB), the photo with bounding boxes and labels, the written assessment with its
source (language model or template), and loading, error and session-expired states. Boxes use
the API's relative coordinates, so they stay aligned at any display size.

## Containers

```bash
make compose-up          # frontend + backend with dummy models: http://localhost:8080
make smoke-test          # end-to-end check of the running stack
make compose-down

make model-fetch         # once: copy the registered "production" detector to ./models
make compose-up-models   # the same stack with the real detector and LLM
```

| Image | Base | Compressed size | Runs as |
| --- | --- | --- | --- |
| `frontend` | `nginx-unprivileged` (Alpine) | 26 MB | uid 101 |
| `serving` | `python:3.12-slim` | 0.3 GB, 1.4 GB with LLM weights | uid 1000 |
| `training` | `nvidia/cuda:13.0-base` | 3.8 GB (CUDA build of PyTorch) | uid 10001 |

All three are multi-stage builds with base images pinned by digest and Python and npm
dependencies installed from the lockfiles. Build tools (uv, Node) stay in the build stages.

- **Serving** takes Ray from `uv.lock` on a slim Python base instead of building on the
  `rayproject/ray` image: about a quarter of the size (that base alone is 0.9 GB
  compressed), no passwordless `sudo` for the container user, and exactly the dependency
  versions the tests ran against. The LLM
  weights are fetched at build time, verified against a pinned SHA-256, and stored in the
  image (`--build-arg LLM=none` leaves them out), so a pod start does not depend on
  Hugging Face.
- **Compose** mirrors the cluster layout: a gateway (nginx here, Envoy Gateway on AKS)
  routes `/api` to the Ray Serve application and everything else to the frontend, limits
  the request size, and applies a coarse rate limit in front of the application's own.
  Containers run with all capabilities dropped; frontend and gateway have read-only
  file systems.
- **Frontend** responses carry a Content-Security-Policy (`default-src 'self'`), and
  hashed assets are cached for a year while the app shell is always revalidated.
- **Training** in a container:
  `docker run --rm --gpus all --ipc=host --user "$(id -u):$(id -g)" -v "$PWD/training/data:/app/data" -v "$PWD/training/runs:/app/runs" -e MLFLOW_TRACKING_URI=<server> roadscan-training:local`.
  It runs `rdd.pipeline` by default; append `rdd.download` or `rdd.prepare` for the data
  steps. The tracking server must be reachable from the container: a local SQLite
  registry records host paths and is not usable from inside it.

CI builds the images and runs the smoke test against the compose stack on every pull
request (serving without the LLM weights, training with CPU-only PyTorch).

## Security

- **Login:** one demo password, compared in constant time. A successful login sets a signed
  session token (JWT, HS256, 60 minutes) in a cookie that is `HttpOnly`, `Secure`,
  `SameSite=Strict` and limited to `/api`. `SameSite=Strict` is the CSRF protection.
- **Secrets:** the password and the signing key are read from files mounted from Azure Key
  Vault (`auth.secrets_dir`), or from `ROADSCAN_DEMO_PASSWORD` / `ROADSCAN_JWT_SECRET` for
  local runs. The API refuses to start without them. Nothing secret is in the repository
  or in an image; the `roadscan-dev` password in the Makefile only exists for local runs.
- **Rate limiting in the application:** login attempts per client address (10 per 5 min),
  analyses per session (6 per min) and per client address (20 per min); `429` with
  `Retry-After`. The client address is taken from `X-Forwarded-For` only as far as our own
  proxies wrote it. A second, coarser limit is enforced at the gateway (Kubernetes
  milestone).
- **Uploads:** 10 MB limit; file type decided by content (JPEG, PNG, WebP), not by name or
  declared type; pixel count checked from the header before decoding (decompression
  bombs); large photos are decoded at reduced size.

## License

Code: [AGPL-3.0-or-later](LICENSE). The detector is trained with Ultralytics YOLO, which is
AGPL-3.0. RDD2022 is licensed CC BY 4.0
(Arya et al., 2022). Model licence notes follow in the final README.
