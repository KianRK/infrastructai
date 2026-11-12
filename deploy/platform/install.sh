#!/usr/bin/env bash
# Installs the cluster-wide components RoadScan relies on, at pinned versions, into the
# cluster of the current kubectl context. Run once per cluster by a cluster admin; safe to
# re-run (also used to upgrade after changing a version below).
#
#   deploy/platform/install.sh
#
# The application itself is the Helm chart in deploy/helm/roadscan.
set -euo pipefail

KUBERAY_VERSION=1.7.2
ENVOY_GATEWAY_VERSION=v1.10.0
CERT_MANAGER_VERSION=v1.21.3

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
helm_install() { helm upgrade --install --create-namespace --wait --timeout 10m "$@"; }

echo "==> Envoy Gateway ${ENVOY_GATEWAY_VERSION} (brings the Gateway API CRDs)"
helm_install envoy-gateway oci://docker.io/envoyproxy/gateway-helm \
  --version "${ENVOY_GATEWAY_VERSION}" --namespace envoy-gateway-system

echo "==> cert-manager ${CERT_MANAGER_VERSION}"
# Gateway API support lets cert-manager answer HTTP-01 challenges through the gateway.
helm_install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  --version "${CERT_MANAGER_VERSION}" --namespace cert-manager \
  --set crds.enabled=true --set config.enableGatewayAPI=true

echo "==> KubeRay operator ${KUBERAY_VERSION}"
helm_install kuberay-operator kuberay-operator \
  --repo https://ray-project.github.io/kuberay-helm/ \
  --version "${KUBERAY_VERSION}" --namespace kuberay-system

echo "==> Gateway class and application namespace"
kubectl apply -f "${here}/cluster/"
