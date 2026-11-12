#!/usr/bin/env bash
# Installs or upgrades the RoadScan Helm release in the cluster of the current kubectl
# context and waits until the application serves.
#
#   scripts/deploy.sh -f deploy/helm/roadscan/values-local.yaml
#   scripts/deploy.sh -f my-values.yaml --set image.tag=<sha>
#
# All arguments are passed to `helm upgrade`. Environment: RELEASE and NAMESPACE (both
# default to "roadscan"), TIMEOUT_SECONDS (default 900). The namespace must exist
# (deploy/platform/install.sh creates it).
set -euo pipefail

RELEASE="${RELEASE:-roadscan}"
NAMESPACE="${NAMESPACE:-roadscan}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-900}"
chart="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/helm/roadscan"

k() { kubectl --namespace "${NAMESPACE}" "$@"; }
rayservice_field() { k get rayservice "${RELEASE}" --ignore-not-found --output "jsonpath=$1"; }
cluster_hash() { rayservice_field '{.metadata.annotations.roadscan/cluster-config-hash}'; }

hash_before="$(cluster_hash)"
helm upgrade --install "${RELEASE}" "${chart}" --namespace "${NAMESPACE}" "$@"
hash_after="$(cluster_hash)"

# With ray.upgrade=InPlace KubeRay leaves a running Ray cluster alone when its definition
# (image, resources, ...) changes. Delete it; KubeRay creates the new one right away.
# Changes to the Serve application config alone are applied by KubeRay without this.
if [[ -n "${hash_before}" && "${hash_before}" != "${hash_after}" \
  && "$(rayservice_field '{.spec.upgradeStrategy.type}')" == "None" ]]; then
  echo "Ray cluster definition changed (${hash_before} -> ${hash_after}): replacing the cluster"
  k delete raycluster --selector "ray.io/originated-from-cr-name=${RELEASE}" --wait
  # The old pods keep answering while they shut down; do not mistake them for the new ones.
  k wait pod --selector ray.io/is-ray-node=yes --for=delete --timeout "${TIMEOUT_SECONDS}s"
fi

echo "Waiting for the frontend and the Ray Serve application (up to ${TIMEOUT_SECONDS}s)"
k rollout status "deployment/${RELEASE}-frontend" --timeout "${TIMEOUT_SECONDS}s"
deadline=$((SECONDS + TIMEOUT_SECONDS))
# Ready = KubeRay reports the application as running on a head pod that exists, is ready
# and is not shutting down.
serving() {
  local status head
  status="$(rayservice_field '{.status.conditions[?(@.type=="Ready")].status}/{.status.activeServiceStatus.applicationStatuses.*.status}')"
  [[ "${status}" == "True/RUNNING" ]] || return 1
  head="$(rayservice_field '{.status.activeServiceStatus.rayClusterStatus.head.podName}')"
  [[ -n "${head}" ]] || return 1
  [[ "$(k get pod "${head}" --ignore-not-found --output \
    'jsonpath={.metadata.deletionTimestamp}/{.status.conditions[?(@.type=="Ready")].status}')" == "/True" ]]
}
until serving; do
  if ((SECONDS >= deadline)); then
    echo "Timed out. State:" >&2
    k get rayservice,raycluster,pods >&2
    k get events --sort-by=.lastTimestamp | tail -n 20 >&2
    exit 1
  fi
  sleep 5
done
echo "RoadScan is serving."
