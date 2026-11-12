#!/usr/bin/env python3
"""Turns the Terraform outputs into Helm values for the AKS deployment.

    terraform -chdir=infra output -json | python3 scripts/aks_values.py \
        | scripts/deploy.sh -f - --set image.tag=<tag>

Reads the JSON on standard input and writes JSON, which Helm accepts as a values file.
None of the values is a secret.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    out = {name: entry["value"] for name, entry in json.load(sys.stdin).items()}
    if not out:
        sys.stderr.write("No Terraform outputs: has `terraform apply` been run in infra/?\n")
        return 1

    pool = {"roadscan/pool": "cpu"}
    values = {
        "image": {"registry": out["acr_login_server"]},
        "host": out["hostname"],
        "gateway": {
            "azure": {
                "publicIpName": out["gateway_public_ip_name"],
                "publicIpResourceGroup": out["resource_group"],
            }
        },
        "secrets": {
            "source": "keyVault",
            "keyVault": {"name": out["key_vault_name"], "tenantId": out["tenant_id"]},
        },
        "serviceAccount": {"workloadIdentityClientId": out["serving_identity_client_id"]},
        "serve": {"mlflowTrackingUri": out["mlflow_tracking_uri"]},
        "ray": {"head": {"nodeSelector": pool}},
        "frontend": {"nodeSelector": pool},
    }
    json.dump(values, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
