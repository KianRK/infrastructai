# RoadScan

End-to-end road damage analysis: upload a road photo, an object detector trained on
RDD2022 localises the damage, and a small self-hosted LLM describes it. Served with
Ray Serve on Azure Kubernetes Service.

> **Status: work in progress.** Milestone 6 of 12 (React frontend). The full
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
cd frontend && npm run dev   # http://localhost:5173, proxies /api to the Serve app on :8000
```

React + TypeScript + Vite. Login screen, image upload with client-side validation (JPEG, PNG,
WebP; 10 MB), the photo with bounding boxes and labels, the written assessment with its
source (language model or template), and loading, error and session-expired states. Boxes use
the API's relative coordinates, so they stay aligned at any display size.

## License

Code: [AGPL-3.0-or-later](LICENSE). The detector is trained with Ultralytics YOLO, which is
AGPL-3.0. RDD2022 is licensed CC BY 4.0
(Arya et al., 2022). Model licence notes follow in the final README.
