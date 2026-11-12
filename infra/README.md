# Infrastructure (Terraform)

Everything RoadScan needs on Azure, in one resource group:

| File | Resources |
| --- | --- |
| `main.tf` | Resource group, sizing profiles, name suffix |
| `aks.tf` | AKS cluster (free control-plane tier, Workload Identity, Key Vault CSI driver, Azure CNI Overlay with Cilium), CPU node pool, optional GPU pool that scales from zero, static public IP with a DNS label |
| `registry.tf` | Container registry (Basic), pull permission for the cluster |
| `ml.tf` | Azure Machine Learning workspace (MLflow tracking and model registry) with its storage account, key vault, Application Insights |
| `keyvault.tf` | Key Vault with the generated secrets `demo-password` and `jwt-secret` |
| `identities.tf` | Managed identities and federated credentials for the serving pods (AKS Workload Identity) and for GitHub Actions (OIDC), role assignments |
| `budget.tf` | Monthly subscription budget with e-mail alerts |

No password, key or client secret is created for any identity. The two application secrets
are generated during `apply` as ephemeral values and written to Key Vault through
write-only arguments, so they are in neither the plan nor the state.

## Sizing profiles

| | `free` (default) | `standard` |
| --- | --- | --- |
| For | Free Trial subscription (4 vCPUs per region, no GPU quota) | Pay-as-you-go |
| System pool | 1 × `Standard_D2ds_v7` (2 vCPU, 8 GB), also runs the operators | 1 × `Standard_D2s_v3`, system pods only |
| CPU pool | 1 × `Standard_D2ds_v7` | 1–2 × `Standard_D8s_v3` (8 vCPU, 32 GB) |
| GPU pool | none | 0–1 × `Standard_NC4as_T4_v3`, spot |
| Automatic upgrades | off (an upgrade needs a spare node, the quota has none) | patch versions and node images |

Every value can be overridden individually; see `variables.tf`.

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) 1.17 or newer and the
  [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli).
- An Azure subscription on which you are **Owner** (the configuration creates role
  assignments).

```bash
az login
az account set --subscription <subscription-id>

# Quotas are only reported once the Compute resource provider is registered.
az provider register --namespace Microsoft.Compute --wait

# Is there quota for 4 vCPUs in the region and in the VM family, and is the size offered
# to this subscription (Restrictions = None)?
az vm list-usage --location westeurope -o table | grep -E 'Total Regional|Ddsv7'
az vm list-skus --location westeurope --size Standard_D2ds_v7 --all -o table
```

If the size is restricted or the quota is short, choose another region (`location`) or
another 2-vCPU size (`system_vm_size`, `cpu_vm_size`). With a size whose cache disk is
smaller than 48 GB, or without one, also set `os_disk_type = "Managed"`.

## Apply

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # ignored by git; fill in
terraform init
terraform plan -out tfplan
terraform apply tfplan                         # about 10-15 minutes
terraform output
```

The state file (`terraform.tfstate`) stays on your machine and is ignored by git. It
contains resource IDs and the budget e-mail addresses, but no secrets. For shared use,
move it to an `azurerm` backend (a storage account outside this configuration).

After the first apply:

1. **Demo password:** `terraform output -raw demo_password_command | sh`. To replace both
   secrets, increase `secrets_version` and apply again.
2. **Register the detector in the workspace** (the local MLflow registry is not reachable
   from the cluster):

   ```bash
   cd training
   uv sync --extra gpu --extra azure
   MLFLOW_TRACKING_URI="$(terraform -chdir=../infra output -raw mlflow_tracking_uri)" \
     uv run python -m rdd.pipeline --weights runs/<run>/weights/best.pt
   ```

3. **GitHub Actions:** the deployment workflow needs the outputs
   `github_identity_client_id`, `tenant_id` and `subscription_id` as repository variables
   (they are identifiers, not secrets).

## Cost

- **Running** (`free` profile): two `Standard_D2ds_v7` nodes, plus the items below.
- **Stopped** (`az aks stop --resource-group rg-roadscan --name aks-roadscan`): the control
  plane and all nodes are deallocated and not billed. Node OS disks are ephemeral, so no
  disks remain. What continues to cost money: the container registry (Basic, a fixed
  daily rate), the static public IP addresses, storage for the model and the images, and
  Log Analytics ingestion (capped at 0.5 GB per day; nothing logs there by default).
- A stopped cluster keeps its state for up to 12 months and can only be started or
  deleted. Wait 15–30 minutes between a stop and the next start
  ([documentation](https://learn.microsoft.com/azure/aks/start-stop-cluster)).
- The budget (`budget_amount`, default 30 per month in the billing currency) sends e-mail
  at 50 %, 80 % and 100 % of actual and 100 % of forecast cost. It notifies only; it does
  not stop anything.

## Destroy

```bash
cd infra
terraform destroy
```

This removes the resource group with everything in it, including resources Terraform did
not create itself (load balancers and disks made by the cluster live in the group
`MC_rg-roadscan_aks-roadscan_<region>`, which Azure deletes with the cluster), and the
budget. Key vaults and the ML workspace are purged, not just soft-deleted, so the names are
free again.

- A **stopped** cluster can be destroyed without starting it.
- Check afterwards: `az group list --query "[?contains(name, 'roadscan')].name" -o tsv`
  prints nothing, and `az keyvault list-deleted -o table` shows no `kv-roadscan-*` vault.
- If `destroy` is interrupted, run it again. As a last resort
  `az group delete --name rg-roadscan` removes everything except the budget
  (`az consumption budget delete --budget-name budget-roadscan`).

## Assumptions and open points

These could not be verified without an active subscription:

- **Free Trial limits.** Checked on a Free Trial subscription in `westeurope` (2026-11):
  4 vCPUs per region, `Standard_D2s_v3` not offered, `Standard_D2ds_v7` offered. Other
  regions and dates may differ; the commands under Prerequisites show the real values.
- **Ephemeral OS disk on NVMe.** `Standard_D2ds_v7` has no cache disk; its ephemeral OS
  disk is placed on the local NVMe disk. If AKS rejects that, set
  `os_disk_type = "Managed"` (a 48 GB disk per node is then billed also while stopped).
- **Budget on a Free Trial.** Cost Management lists the Free Trial offer as supported; if
  creating the budget fails, set `budget_enabled = false`.
- **MLflow model aliases.** Serving loads `models:/roadscan-detector@production`. Azure
  ML's documentation lists loading by version, `latest` and stage, but does not mention
  aliases. This is tested right after the first registration (step 2 fails at the alias
  call if they are unsupported); the fallback is a version tag.
- **Cluster stop/start by GitHub Actions.** The workflow identity has the
  `Azure Kubernetes Service Contributor Role`; that it covers stop and start is checked
  with the deployment workflow.
- **Resource provider registration.** The provider registers the usual set
  (`resource_provider_registrations = "extended"`); on a new subscription the first
  apply may need a second run if a registration is still in progress.
