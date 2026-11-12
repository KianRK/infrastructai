# Monthly budget on the whole subscription (the cluster's nodes live in a second resource
# group that AKS manages, so a budget on rg-<name> alone would miss most of the cost).
# A budget only notifies; it does not stop anything.
resource "azurerm_consumption_budget_subscription" "main" {
  count = var.budget_enabled ? 1 : 0

  name            = "budget-${var.name}"
  subscription_id = data.azurerm_subscription.current.id
  amount          = var.budget_amount
  time_grain      = "Monthly"

  time_period {
    # Must be the first day of a month; fixed at creation.
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", plantimestamp())
  }

  dynamic "notification" {
    for_each = {
      half     = { threshold = 50, type = "Actual" }
      most     = { threshold = 80, type = "Actual" }
      all      = { threshold = 100, type = "Actual" }
      forecast = { threshold = 100, type = "Forecasted" }
    }
    content {
      operator       = "GreaterThanOrEqualTo"
      threshold      = notification.value.threshold
      threshold_type = notification.value.type
      contact_emails = var.budget_contact_emails
    }
  }

  lifecycle {
    ignore_changes = [time_period]
  }
}
