#!/usr/bin/env bash
# Starts and stops the AKS cluster of the on-demand demo.
#
#   scripts/demo.sh up [hours]   start the cluster (if stopped) and schedule its stop
#   scripts/demo.sh down         stop the cluster now
#   scripts/demo.sh status       power state and scheduled stop
#   scripts/demo.sh auto-stop    stop the cluster if its scheduled stop has passed
#   scripts/demo.sh latest-tag <registry>   newest serving image tag in the registry
#
# A stopped cluster is not billed for its control plane or nodes. The scheduled stop is
# kept in the cluster's Azure tag "demo-stop-at" (UTC); the "Demo" GitHub workflow runs
# `auto-stop` every half hour. A running cluster without a valid tag counts as overdue,
# so a cluster started in any other way is stopped as well.
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
  # `az aks update --tags` replaces all tags: pass the existing ones along.
  local -a tags
  mapfile -t tags < <(aks show --query tags --output json | python3 -c '
import json, sys
tags = json.load(sys.stdin) or {}
tags[sys.argv[1]] = sys.argv[2]
print("\n".join(f"{key}={value}" for key, value in tags.items()))' "${STOP_TAG}" "${when}")
  aks update --tags "${tags[@]}" --output none
  echo "The cluster will be stopped automatically after ${when}."
}

case "${1:-}" in
  up)
    hours="${2:-2}"
    if ! [[ "${hours}" =~ ^[0-9]+$ ]] || ((hours < 1 || hours > MAX_HOURS)); then
      echo "hours must be a whole number from 1 to ${MAX_HOURS}" >&2
      exit 2
    fi
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
    schedule_stop "${hours}"
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
  auto-stop)
    if [[ "$(power_state)" != "Running" ]]; then
      echo "The cluster is not running; nothing to do."
      exit 0
    fi
    when="$(stop_at)"
    # An unreadable or missing tag yields 0: overdue.
    deadline="$(date --utc --date "${when:-invalid}" +%s 2>/dev/null || echo 0)"
    if (($(date +%s) >= deadline)); then
      echo "Scheduled stop '${when}' has passed (or is missing): stopping ${CLUSTER}"
      aks stop --output none
    else
      echo "The cluster stays up until ${when}."
    fi
    ;;
  latest-tag)
    registry="${2:?usage: demo.sh latest-tag <registry login server>}"
    az acr repository show-tags --name "${registry%%.*}" --repository roadscan-serving \
      --orderby time_desc --query "[?!starts_with(@, 'buildcache')] | [0]" --output tsv
    ;;
  *)
    sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
    exit 2
    ;;
esac
