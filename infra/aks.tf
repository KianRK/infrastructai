resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-${var.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  dns_prefix          = var.name
  kubernetes_version  = var.kubernetes_version
  sku_tier            = "Free" # no charge for the control plane
  tags                = local.tags

  automatic_upgrade_channel = local.profile.upgrade_channel
  node_os_upgrade_channel   = local.profile.upgrade_channel == null ? "None" : "NodeImage"

  # Access: Entra ID only, authorised through Azure role assignments (identities.tf).
  local_account_disabled            = true
  role_based_access_control_enabled = true
  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = data.azurerm_client_config.current.tenant_id
  }

  # Pods obtain Azure tokens through their service account (identities.tf).
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  # Secrets Store CSI driver with the Key Vault provider.
  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }

  identity {
    type = "SystemAssigned"
  }

  # Node pools are defined here, not provisioned automatically: clusters with node
  # auto-provisioning cannot be stopped, which the on-demand demo depends on.
  node_provisioning_profile {
    mode = "Manual"
  }

  default_node_pool {
    name                         = "system"
    vm_size                      = local.system_vm_size
    node_count                   = 1
    os_disk_type                 = var.os_disk_type
    os_disk_size_gb              = var.os_disk_size_gb
    only_critical_addons_enabled = local.profile.system_tainted
    temporary_name_for_rotation  = "systemtmp"
    tags                         = local.tags

    # The value Azure sets by default; stated so that plans show no difference.
    upgrade_settings {
      max_surge = "10%"
    }
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium" # enforces Kubernetes network policies
    load_balancer_sku   = "standard"
  }

  lifecycle {
    # Written by scripts/demo.sh: when the running demo is stopped automatically.
    ignore_changes = [tags["demo-stop-at"]]
  }
}

# CPU pool: Ray head and workers (detector, LLM), frontend.
resource "azurerm_kubernetes_cluster_node_pool" "cpu" {
  name                  = "cpu"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  mode                  = "User"
  vm_size               = local.cpu_vm_size
  os_disk_type          = var.os_disk_type
  os_disk_size_gb       = var.os_disk_size_gb
  auto_scaling_enabled  = true
  min_count             = 1
  max_count             = local.cpu_node_max
  node_labels           = { "roadscan/pool" = "cpu" }
  # Without the taint the scheduler may fill this node with cluster add-ons (after a
  # stop/start both nodes come up empty) and the Ray pod no longer fits.
  node_taints = local.profile.cpu_tainted ? ["roadscan/pool=cpu:NoSchedule"] : null
  tags        = local.tags

  upgrade_settings {
    max_surge = "10%"
  }
}

# GPU pool for the optional vLLM backend. No nodes, and no cost, until a pod asks for a GPU.
resource "azurerm_kubernetes_cluster_node_pool" "gpu" {
  count = local.gpu_node_max > 0 ? 1 : 0

  name                  = "gpu"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  mode                  = "User"
  vm_size               = var.gpu_vm_size
  os_disk_type          = "Managed" # GPU sizes differ in cache disk size
  os_disk_size_gb       = 128       # the vLLM image and model weights are large
  auto_scaling_enabled  = true
  min_count             = 0
  max_count             = local.gpu_node_max
  node_labels           = { "roadscan/pool" = "gpu" }
  node_taints           = ["sku=gpu:NoSchedule"]
  tags                  = local.tags

  priority        = var.gpu_spot ? "Spot" : "Regular"
  eviction_policy = var.gpu_spot ? "Delete" : null
  spot_max_price  = var.gpu_spot ? -1 : null # pay up to the on-demand price
}

# Public address of the gateway, with a free Azure DNS name:
#   <label>.<region>.cloudapp.azure.com
resource "azurerm_public_ip" "gateway" {
  name                = "pip-${var.name}-gateway"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  allocation_method   = "Static"
  sku                 = "Standard"
  domain_name_label   = "${var.name}-${local.suffix}"
  tags                = local.tags
}

# The cluster attaches that address to its load balancer.
resource "azurerm_role_assignment" "aks_uses_gateway_ip" {
  scope                = azurerm_public_ip.gateway.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_kubernetes_cluster.main.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}
