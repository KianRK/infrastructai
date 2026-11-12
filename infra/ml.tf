# Azure Machine Learning workspace: MLflow tracking server and model registry.
# It requires a storage account, a key vault and Application Insights of its own.

resource "azurerm_storage_account" "ml" {
  name                            = "st${var.name}${local.suffix}"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = local.tags
}

resource "azurerm_key_vault" "ml" {
  name                       = "kv-${var.name}-ml-${local.suffix}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  tags                       = local.tags
}

resource "azurerm_log_analytics_workspace" "ml" {
  name                = "log-${var.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.5 # hard stop; nothing in this project logs here by default
  tags                = local.tags
}

resource "azurerm_application_insights" "ml" {
  name                = "appi-${var.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  workspace_id        = azurerm_log_analytics_workspace.ml.id
  application_type    = "web"
  tags                = local.tags
}

resource "azurerm_machine_learning_workspace" "main" {
  name                          = "mlw-${var.name}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  sku_name                      = "Basic"
  storage_account_id            = azurerm_storage_account.ml.id
  key_vault_id                  = azurerm_key_vault.ml.id
  application_insights_id       = azurerm_application_insights.ml.id
  public_network_access_enabled = true # reached from the laptop and from the cluster
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }
}
