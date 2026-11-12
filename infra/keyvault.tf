# Application secrets: the demo password and the session signing key.
resource "azurerm_key_vault" "app" {
  name                       = "kv-${var.name}-app-${local.suffix}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false # a demo vault must be removable by terraform destroy
  tags                       = local.tags
}

# Whoever runs Terraform may write and read the secrets (e.g. to look up the password).
resource "azurerm_role_assignment" "operator_manages_secrets" {
  scope                = azurerm_key_vault.app.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Role assignments take a moment to become effective.
resource "time_sleep" "secrets_role_effective" {
  create_duration = "60s"
  depends_on      = [azurerm_role_assignment.operator_manages_secrets]
}

# Generated on the fly and passed to write-only arguments: the values are stored in Key
# Vault only, not in the Terraform state or plan.
ephemeral "random_password" "demo_password" {
  length  = 20
  special = false
}

ephemeral "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "azurerm_key_vault_secret" "demo_password" {
  name             = "demo-password"
  key_vault_id     = azurerm_key_vault.app.id
  value_wo         = ephemeral.random_password.demo_password.result
  value_wo_version = var.secrets_version
  content_type     = "text/plain"
  tags             = local.tags

  depends_on = [time_sleep.secrets_role_effective]
}

resource "azurerm_key_vault_secret" "jwt_secret" {
  name             = "jwt-secret"
  key_vault_id     = azurerm_key_vault.app.id
  value_wo         = ephemeral.random_password.jwt_secret.result
  value_wo_version = var.secrets_version
  content_type     = "text/plain"
  tags             = local.tags

  depends_on = [time_sleep.secrets_role_effective]
}
