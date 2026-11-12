terraform {
  required_version = "~> 1.17"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.13"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
  }

  # State is kept locally (terraform.tfstate, ignored by git). One person, one
  # environment; see README.md for moving it to an Azure storage backend.
}

provider "azurerm" {
  subscription_id = var.subscription_id

  # A new subscription has few resource providers registered; let Terraform register the
  # commonly used set.
  resource_provider_registrations = "extended"
  # Not part of that set.
  resource_providers_to_register = ["Microsoft.MachineLearningServices"]

  features {
    resource_group {
      # AKS, Azure ML and the gateway create resources Terraform does not track.
      # `terraform destroy` must still be able to remove the group.
      prevent_deletion_if_contains_resources = false
    }
    key_vault {
      # Free the vault names again on destroy instead of leaving soft-deleted vaults.
      purge_soft_delete_on_destroy = true
    }
    machine_learning {
      purge_soft_deleted_workspace_on_destroy = true
    }
  }
}
