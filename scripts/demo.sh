#!/usr/bin/env bash
# Starts and stops the AKS cluster of the on-demand demo.
#
#   scripts/demo.sh up [hours]   start the cluster (if stopped) and schedule its stop
#   scripts/demo.sh down         stop the cluster now
#   scripts/demo.sh status       power state and scheduled stop
#   scripts/demo.sh latest-tag <registry>   newest serving image tag in the registry
#
# A stopped cluster is not billed for its control plane or nodes. The scheduled stop is
# kept in the cluster's Azure tag "demo-stop-at" (UTC); a Logic App in Azure
# (infra/autostop.tf) checks it every 15 minutes. A running cluster without the tag
# counts as overdue, so a cluster started in any other way is stopped as well.
#
# Environment: RESOURCE_GROUP (default rg-roadscan), CLUSTER (default aks-roadscan).
# Needs the Azure CLI, logged in.
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-roadscan}"
CLUSTER="${CLUSTER:-aks-roadscan}"
STOP_TAG="demo-stop-at"
MAX_HOURS=12

aks() { az aks "$1" --resource-group "${RESOURCE_GROUP}" --name "${CLUSTER}" "${@:2}"; }
power_state() { aks show --query powerState.code --output tsv; }
stop_at() { aks show --query "tags.\"${STOP_TAG}\"" --output tsv; }

schedule_stop() {
  local hours="$1" when
  when="$(date --utc --date "+${hours} hours" +%Y-%m-%dT%H:%M:%SZ)"
  # The tags API changes one tag and, unlike `az aks update`, works on a stopped cluster.
  az tag update --resource-id "$(aks show --query id --output tsv)" --operation Merge \
    --tags "${STOP_TAG}=${when}" --output none
  echo "The cluster will be stopped automatically after ${when}."
}

case "${1:-}" in
  up)
    hours="${2:-2}"
    if ! [[ "${hours}" =~ ^[0-9]+$ ]] || ((hours < 1 || hours > MAX_HOURS)); then
      echo "hours must be a whole number from 1 to ${MAX_HOURS}" >&2
      exit 2
    fi
    # First the stop time, then the start: the automatic stop never sees a running
    # cluster with the stop time of the previous run.
    schedule_stop "${hours}"
    if [[ "$(power_state)" == "Running" ]]; then
      echo "The cluster is already running."
    else
      echo "Starting ${CLUSTER} (takes a few minutes)"
      if ! aks start --output none; then
        echo "Start failed. After a stop, Azure needs 15-30 minutes before the cluster" \
          "can be started again; retry later." >&2
        exit 1
      fi
    fi
    ;;
  down)
    if [[ "$(power_state)" == "Stopped" ]]; then
      echo "The cluster is already stopped."
    else
      echo "Stopping ${CLUSTER} (takes a few minutes)"
      aks stop --output none
      echo "Stopped. Wait 15-30 minutes before starting it again."
    fi
    ;;
  status)
    echo "power state:    $(power_state)"
    echo "scheduled stop: $(stop_at || true)"
    ;;
  latest-tag)
    registry="${2:?usage: demo.sh latest-tag <registry login server>}"
    az acr repository show-tags --name "${registry%%.*}" --repository roadscan-serving \
      --orderby time_desc --query "[?!starts_with(@, 'buildcache')] | [0]" --output tsv
    ;;
  *)
    sed -n '2,7p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
    exit 2
    ;;
esac
