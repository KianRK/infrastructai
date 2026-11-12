data "azurerm_client_config" "current" {}

data "azurerm_subscription" "current" {}

locals {
  profiles = {
    # Free Trial: 4 vCPUs in total and none for GPUs. Two 2-vCPU nodes use all of it, so
    # there is no room for the extra node an automatic upgrade needs.
    free = {
      system_vm_size  = "Standard_D2s_v3" # 2 vCPU, 8 GB
      cpu_vm_size     = "Standard_D2s_v3"
      cpu_node_max    = 1
      gpu_node_max    = 0
      system_tainted  = false # operators (gateway, cert-manager, KubeRay) may use it
      upgrade_channel = null
    }
    standard = {
      system_vm_size  = "Standard_D2s_v3"
      cpu_vm_size     = "Standard_D8s_v3" # 8 vCPU, 32 GB
      cpu_node_max    = 2
      gpu_node_max    = 1
      system_tainted  = true
      upgrade_channel = "patch"
    }
  }
  profile = local.profiles[var.sizing_profile]

  system_vm_size = coalesce(var.system_vm_size, local.profile.system_vm_size)
  cpu_vm_size    = coalesce(var.cpu_vm_size, local.profile.cpu_vm_size)
  cpu_node_max   = coalesce(var.cpu_node_max, local.profile.cpu_node_max)
  gpu_node_max   = coalesce(var.gpu_node_max, local.profile.gpu_node_max)

  # Globally unique names (registry, storage, vaults, DNS label) get a random suffix.
  suffix = random_string.suffix.result

  tags = merge({ project = var.name, managed-by = "terraform" }, var.tags)
}

resource "random_string" "suffix" {
  length  = 5
  lower   = true
  numeric = true
  upper   = false
  special = false
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.name}"
  location = var.location
  tags     = local.tags
}
