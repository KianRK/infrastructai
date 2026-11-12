# syntax=docker/dockerfile:1
# Serving image: Ray Serve application (API, detector, LLM) on the official Ray image.
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

# --- Runtime: the official Ray image ----------------------------------------------------
# Same Ray version as uv.lock; KubeRay requires the image's Ray to match the cluster's.
FROM rayproject/ray:2.59.1-py312-cpu@sha256:8c94fda2eb9636fba81e850337db5db023e23fcc830ce2d547b9698a5c2ffb2b

# The base image lets its user become root without a password (a rule in /etc/sudoers).
# Remove sudo altogether.
USER root
RUN SUDO_FORCE_REMOVE=yes apt-get purge -y sudo \
    && rm -rf /etc/sudoers /etc/sudoers.d /var/lib/apt/lists/* \
    && gpasswd --delete ray sudo \
    && mkdir /app && chown ray:users /app
USER 1000:100
WORKDIR /app

# Weights before dependencies and code: this 1.1 GB layer is then reused across changes.
COPY --from=llm /models /opt/models

# Install the locked dependencies into the base image's Python environment, replacing its
# versions where the lockfile differs (--inexact keeps the packages only the base has).
# uv is mounted for these steps and not kept in the image.
ENV UV_PROJECT_ENVIRONMENT=/home/ray/anaconda3 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/home/ray/.cache/uv,uid=1000,gid=100 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --extra azure --inexact --no-install-project
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/home/ray/.cache/uv,uid=1000,gid=100 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=src,target=src \
    uv sync --locked --no-dev --extra azure --inexact --no-editable
COPY config config
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
# On Kubernetes, KubeRay supplies the command; this default is for docker compose.
CMD ["serve", "run", "config/serve.docker.yaml"]
