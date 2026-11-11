# RoadScan

End-to-end road damage analysis: upload a road photo, an object detector trained on
RDD2022 localises the damage, and a small self-hosted LLM describes it. Served with
Ray Serve on Azure Kubernetes Service.

> **Status: work in progress.** Milestone 1 of 12 (repo skeleton, tooling, CI). The full
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
make install   # uv sync for both Python projects, npm ci for the frontend
make check     # lint + type-check + tests, the same steps CI runs
make help      # all targets
```

Optional: `uvx pre-commit install` to run ruff on every commit.

## License

Code: [AGPL-3.0-or-later](LICENSE). The detector is trained with Ultralytics YOLO, which is
AGPL-3.0. Dataset and model licence notes follow in the final README.
