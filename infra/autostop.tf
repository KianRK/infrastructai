# Automatic stop of the on-demand demo.
#
# scripts/demo.sh writes the time of the stop into the cluster's tag "demo-stop-at" (UTC).
# A Logic App checks it every 15 minutes and stops the cluster once that time has passed.
# It runs in Azure, independent of the machine or workflow that started the demo. A
# running cluster without the tag counts as overdue, so a cluster started in any other
# way (`az aks start`, `terraform apply`) is stopped as well.

locals {
  autostop_cluster_url = "https://management.azure.com${azurerm_kubernetes_cluster.main.id}"
  autostop_api_version = "2026-06-01"
  autostop_identity    = { type = "ManagedServiceIdentity", audience = "https://management.azure.com/" }

  # Workflow-definition expressions over the answer of the "Get_cluster" action.
  autostop_stop_at = "body('Get_cluster')?['tags']?['demo-stop-at']"
  autostop_overdue = "@or(empty(${local.autostop_stop_at}), less(ticks(${local.autostop_stop_at}), ticks(utcNow())))"
}

# The only two operations the Logic App needs: read the cluster, stop it.
resource "azurerm_role_definition" "autostop" {
  name        = "${var.name}-cluster-stop"
  scope       = azurerm_resource_group.main.id
  description = "Read an AKS cluster and stop it."

  permissions {
    actions = [
      "Microsoft.ContainerService/managedClusters/read",
      "Microsoft.ContainerService/managedClusters/stop/action",
    ]
  }

  assignable_scopes = [azurerm_resource_group.main.id]
}

resource "azurerm_logic_app_workflow" "autostop" {
  name                = "logic-${var.name}-autostop"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_role_assignment" "autostop_stops_cluster" {
  scope              = azurerm_kubernetes_cluster.main.id
  role_definition_id = azurerm_role_definition.autostop.role_definition_resource_id
  principal_id       = azurerm_logic_app_workflow.autostop.identity[0].principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_logic_app_trigger_recurrence" "autostop" {
  name         = "Every_15_minutes"
  logic_app_id = azurerm_logic_app_workflow.autostop.id
  frequency    = "Minute"
  interval     = 15
}

resource "azurerm_logic_app_action_custom" "autostop_get_cluster" {
  name         = "Get_cluster"
  logic_app_id = azurerm_logic_app_workflow.autostop.id

  body = jsonencode({
    type = "Http"
    inputs = {
      method         = "GET"
      uri            = local.autostop_cluster_url
      queries        = { "api-version" = local.autostop_api_version }
      authentication = local.autostop_identity
    }
    runAfter = {}
  })
}

resource "azurerm_logic_app_action_custom" "autostop_stop_if_overdue" {
  name         = "Stop_if_overdue"
  logic_app_id = azurerm_logic_app_workflow.autostop.id

  body = jsonencode({
    type = "If"
    # Only a cluster that is up and idle: while it starts, stops or is being updated
    # the provisioning state is not "Succeeded" and the check waits for the next round.
    expression = {
      and = [
        { equals = ["@body('Get_cluster')?['properties']?['powerState']?['code']", "Running"] },
        { equals = ["@body('Get_cluster')?['properties']?['provisioningState']", "Succeeded"] },
        { equals = [local.autostop_overdue, true] },
      ]
    }
    actions = {
      Stop_cluster = {
        type = "Http"
        inputs = {
          method         = "POST"
          uri            = "${local.autostop_cluster_url}/stop"
          queries        = { "api-version" = local.autostop_api_version }
          authentication = local.autostop_identity
        }
        runAfter = {}
      }
    }
    runAfter = { Get_cluster = ["Succeeded"] }
  })

  depends_on = [azurerm_logic_app_action_custom.autostop_get_cluster]
}
