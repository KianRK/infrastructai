output "resource_group" {
  value = azurerm_resource_group.main.name
}

output "aks_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "hostname" {
  description = "Public DNS name of the demo."
  value       = azurerm_public_ip.gateway.fqdn
}

output "gateway_public_ip" {
  value = azurerm_public_ip.gateway.ip_address
}

output "gateway_public_ip_name" {
  value = azurerm_public_ip.gateway.name
}

output "key_vault_name" {
  description = "Vault holding demo-password and jwt-secret."
  value       = azurerm_key_vault.app.name
}

output "tenant_id" {
  value = data.azurerm_client_config.current.tenant_id
}

output "subscription_id" {
  value = data.azurerm_subscription.current.subscription_id
}

output "serving_identity_client_id" {
  description = "For the service account annotation and the SecretProviderClass."
  value       = azurerm_user_assigned_identity.serving.client_id
}

output "github_identity_client_id" {
  description = "AZURE_CLIENT_ID for the GitHub Actions workflows."
  value       = azurerm_user_assigned_identity.github.client_id
}

output "mlflow_tracking_uri" {
  description = "MLFLOW_TRACKING_URI of the Azure ML workspace (needs the azureml-mlflow plugin)."
  value       = "azureml://${azurerm_resource_group.main.location}.api.azureml.ms/mlflow/v1.0${azurerm_machine_learning_workspace.main.id}"
}

output "demo_password_command" {
  description = "Prints the demo password."
  value       = "az keyvault secret show --vault-name ${azurerm_key_vault.app.name} --name demo-password --query value -o tsv"
}
