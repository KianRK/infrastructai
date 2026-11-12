# --- Serving pods ----------------------------------------------------------------------
# The Ray pods run under a Kubernetes service account that is federated with this
# identity (AKS Workload Identity). No credential is stored anywhere.

resource "azurerm_user_assigned_identity" "serving" {
  name                = "id-${var.name}-serving"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "serving" {
  name                      = "aks-${var.kubernetes_namespace}-${var.serving_service_account}"
  user_assigned_identity_id = azurerm_user_assigned_identity.serving.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject                   = "system:serviceaccount:${var.kubernetes_namespace}:${var.serving_service_account}"
}

# Read the demo password and the signing key (mounted by the Secrets Store CSI driver).
resource "azurerm_role_assignment" "serving_reads_secrets" {
  scope                = azurerm_key_vault.app.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.serving.principal_id
  principal_type       = "ServicePrincipal"
}

# Download the registered detector from the Azure ML model registry.
resource "azurerm_role_assignment" "serving_reads_models" {
  scope                = azurerm_machine_learning_workspace.main.id
  role_definition_name = "AzureML Data Scientist"
  principal_id         = azurerm_user_assigned_identity.serving.principal_id
  principal_type       = "ServicePrincipal"
}

# --- GitHub Actions ----------------------------------------------------------------------
# Workflows log in with a short-lived OIDC token issued by GitHub; no client secret.

resource "azurerm_user_assigned_identity" "github" {
  name                = "id-${var.name}-github"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "github" {
  for_each = var.github_subjects

  name                      = "github-${each.key}"
  user_assigned_identity_id = azurerm_user_assigned_identity.github.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "${var.github_subject_prefix}:${each.value}"
}

resource "azurerm_role_assignment" "github_pushes_images" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
  principal_type       = "ServicePrincipal"
}

# Fetch cluster credentials, and start and stop the cluster (on-demand demo).
resource "azurerm_role_assignment" "github_operates_cluster" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service Contributor Role"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
  principal_type       = "ServicePrincipal"
}

# Deploy the application: full rights inside its namespace, none outside.
resource "azurerm_role_assignment" "github_deploys_app" {
  scope                = "${azurerm_kubernetes_cluster.main.id}/namespaces/${var.kubernetes_namespace}"
  role_definition_name = "Azure Kubernetes Service RBAC Admin"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
  principal_type       = "ServicePrincipal"
}

# Read the demo password for the post-deployment smoke test: this one secret only.
resource "azurerm_role_assignment" "github_reads_demo_password" {
  scope                = azurerm_key_vault_secret.demo_password.resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
  principal_type       = "ServicePrincipal"
}

# --- The person running Terraform ---------------------------------------------------------

resource "azurerm_role_assignment" "operator_administers_cluster" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Register models from the laptop.
resource "azurerm_role_assignment" "operator_registers_models" {
  scope                = azurerm_machine_learning_workspace.main.id
  role_definition_name = "AzureML Data Scientist"
  principal_id         = data.azurerm_client_config.current.object_id
}
