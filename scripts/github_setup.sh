#!/usr/bin/env bash
# Writes the repository secrets the CD and Demo workflows read, from the Terraform outputs.
#
#   scripts/github_setup.sh
#
# None of the four is a credential: three identifiers for the OIDC login and the Helm
# values of the deployment. They are stored as secrets because the workflow logs of a
# public repository are public. Needs `gh` (logged in, with admin rights on the
# repository), `terraform` with the local state of ./infra, and python3.
# Run again after `terraform apply` changed an output.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output() { terraform -chdir="${root}/infra" output -raw "$1"; }

output github_identity_client_id | gh secret set AZURE_CLIENT_ID
output tenant_id | gh secret set AZURE_TENANT_ID
output subscription_id | gh secret set AZURE_SUBSCRIPTION_ID
# One line, so that GitHub masks it as a whole.
terraform -chdir="${root}/infra" output -json \
  | python3 "${root}/scripts/aks_values.py" \
  | python3 -c 'import json, sys; print(json.dumps(json.load(sys.stdin), separators=(",", ":")))' \
  | gh secret set AKS_HELM_VALUES
echo "Secrets written. The workflows can now log in to Azure and deploy."
