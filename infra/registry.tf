# Container registry for the serving and frontend images. Basic: 10 GB included.
resource "azurerm_container_registry" "main" {
  name                = "acr${var.name}${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false # no shared password; pulls and pushes use Entra identities
  tags                = local.tags
}

# The cluster's nodes pull images with their own identity.
resource "azurerm_role_assignment" "aks_pulls_images" {
  scope                            = azurerm_container_registry.main.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.main.kubelet_identity[0].object_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}
