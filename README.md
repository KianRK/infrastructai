# RoadScan

End-to-end road damage analysis: upload a road photo, an object detector trained on
RDD2022 localises the damage, and a small self-hosted LLM describes it. Served with
Ray Serve on Azure Kubernetes Service.

> **Status: work in progress.** Milestone 2 of 12 (data pipeline). The full
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

## License

Code: [AGPL-3.0-or-later](LICENSE). The detector is trained with Ultralytics YOLO, which is
AGPL-3.0. RDD2022 is licensed CC BY 4.0
(Arya et al., 2022). Model licence notes follow in the final README.
