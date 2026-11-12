#!/usr/bin/env bash
# Builds the serving and frontend images and pushes them to an Azure container registry.
#
#   scripts/push_images.sh <registry login server> <tag>
#
# Needs `az login` with push rights on the registry (AcrPush).
set -euo pipefail

registry="${1:?usage: push_images.sh <registry login server> <tag>}"
tag="${2:?usage: push_images.sh <registry login server> <tag>}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

az acr login --name "${registry%%.*}"
for image in serving frontend; do
  docker build --tag "${registry}/roadscan-${image}:${tag}" "${root}/${image}"
  docker push "${registry}/roadscan-${image}:${tag}"
done
