# syntax=docker/dockerfile:1
# Training image: data pipeline and detector training on an NVIDIA GPU.
#   docker build -t roadscan-training training
#   docker run --rm --gpus all --ipc=host -v "$PWD/training/data:/app/data" \
#     -v "$PWD/training/runs:/app/runs" -e MLFLOW_TRACKING_URI=... roadscan-training
#
# The "base" flavour of the CUDA image is enough: the PyTorch wheels bring their own CUDA
# libraries, the image only has to provide the driver hooks.

# gpu: CUDA build of PyTorch. cpu: CPU-only build (CI build check, smoke tests).
ARG TORCH=gpu

FROM nvidia/cuda:13.0.2-base-ubuntu24.04@sha256:2ab6381d970b211fb93853796dc6707eb8a72575a375c422b17cf4d8b2641701 AS base

# --- Build: Python and the locked dependencies -------------------------------------------
FROM base AS build
ARG TORCH
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=.python-version,target=.python-version \
    uv sync --locked --no-dev --extra "${TORCH}" --extra azure --no-install-project
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=.python-version,target=.python-version \
    --mount=type=bind,source=src,target=src \
    uv sync --locked --no-dev --extra "${TORCH}" --extra azure --no-editable

# --- Runtime ------------------------------------------------------------------------------
FROM base
# Shared libraries OpenCV loads at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home trainer \
    && mkdir -p /app/data /app/runs && chown -R trainer:trainer /app && chmod -R a+rwX /app
COPY --from=build /opt/python /opt/python
COPY --from=build /app/.venv /app/.venv
WORKDIR /app
COPY configs configs
# /app is writable for any user and caches go to /tmp, so the image also works with
# `--user $(id -u):$(id -g)` and bind-mounted data.
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib
USER 10001:10001
ENTRYPOINT ["python", "-m"]
CMD ["rdd.pipeline"]
