# syntax=docker/dockerfile:1
# Serving image: Ray Serve application (API, detector, LLM).
# Ray comes from uv.lock like every other dependency, on a slim Python base: about a
# quarter of the size of a build on the rayproject/ray image, and the tested versions.
#   docker build -t roadscan-serving serving                      # with the LLM weights
#   docker build -t roadscan-serving --build-arg LLM=none serving # without (dummy LLM, CI)

# "baked" stores the LLM weights in the image, "none" leaves them out.
ARG LLM=baked

# --- LLM weights: fetched by BuildKit and verified against a pinned checksum ------------
FROM scratch AS llm-baked
ARG LLM_REPO=Qwen/Qwen2.5-1.5B-Instruct-GGUF
ARG LLM_REVISION=91cad51170dc346986eccefdc2dd33a9da36ead9
ARG LLM_FILE=qwen2.5-1.5b-instruct-q4_k_m.gguf
ADD --chmod=444 \
    --checksum=sha256:6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e \
    https://huggingface.co/${LLM_REPO}/resolve/${LLM_REVISION}/${LLM_FILE} /models/${LLM_FILE}

FROM scratch AS llm-none
WORKDIR /models

FROM llm-${LLM} AS llm

FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base

# --- Build: the locked dependencies and the application, in a virtual environment ------
FROM base AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --extra azure --no-install-project
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=src,target=src \
    uv sync --locked --no-dev --extra azure --no-editable

# --- Runtime ------------------------------------------------------------------------------
FROM base
# wget: used by the container health checks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home ray \
    && mkdir /app && chown ray:ray /app
# Weights before code: this 1.1 GB layer is then reused across code changes.
COPY --from=llm /models /opt/models
COPY --from=build /app/.venv /app/.venv
WORKDIR /app
COPY config config
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
USER 1000:1000

EXPOSE 8000
# On Kubernetes, KubeRay supplies the command; this default is for docker compose.
CMD ["serve", "run", "config/serve.docker.yaml"]
