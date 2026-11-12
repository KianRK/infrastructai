variable "subscription_id" {
  description = "Azure subscription to deploy into."
  type        = string
}

variable "location" {
  description = "Azure region. Check VM quota there first (see README.md)."
  type        = string
  default     = "westeurope"
}

variable "name" {
  description = "Short name used in all resource names."
  type        = string
  default     = "roadscan"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,9}$", var.name))
    error_message = "Use 3-10 lowercase letters and digits, starting with a letter."
  }
}

variable "sizing_profile" {
  description = <<-EOT
    Sizing profile.
    free:     fits a Free Trial subscription (4 vCPUs in total, no GPU quota).
    standard: larger CPU node and an optional GPU pool; needs a pay-as-you-go subscription.
  EOT
  type        = string
  default     = "free"

  validation {
    condition     = contains(["free", "standard"], var.sizing_profile)
    error_message = "sizing_profile must be \"free\" or \"standard\"."
  }
}

# --- Overrides of the profile values (null = take the profile's value) -----------------

variable "system_vm_size" {
  description = "VM size of the system node pool."
  type        = string
  default     = null
}

variable "cpu_vm_size" {
  description = "VM size of the CPU user node pool (Ray head and workers, frontend)."
  type        = string
  default     = null
}

variable "cpu_node_max" {
  description = "Upper limit of the CPU user node pool autoscaler (lower limit is 1)."
  type        = number
  default     = null
}

variable "gpu_node_max" {
  description = "Upper limit of the GPU node pool, which scales from zero. 0 = no GPU pool."
  type        = number
  default     = null
}

variable "gpu_vm_size" {
  description = "VM size of the GPU node pool."
  type        = string
  default     = "Standard_NC4as_T4_v3"
}

variable "gpu_spot" {
  description = "Run GPU nodes as spot instances (much cheaper, can be evicted)."
  type        = bool
  default     = true
}

variable "os_disk_type" {
  description = <<-EOT
    Ephemeral: the OS disk lives on the VM's local cache disk, costs nothing, and is not
    billed while the cluster is stopped. Needs a VM size whose cache disk is at least
    os_disk_size_gb. Managed: works with every VM size, billed also while stopped.
  EOT
  type        = string
  default     = "Ephemeral"

  validation {
    condition     = contains(["Ephemeral", "Managed"], var.os_disk_type)
    error_message = "os_disk_type must be \"Ephemeral\" or \"Managed\"."
  }
}

variable "os_disk_size_gb" {
  description = "OS disk size of all nodes. The serving image alone unpacks to about 6 GB."
  type        = number
  default     = 48
}

variable "kubernetes_version" {
  description = "Kubernetes minor version, e.g. \"1.34\". null = the AKS default at creation."
  type        = string
  default     = null
}

# --- Access ----------------------------------------------------------------------------

variable "github_repository" {
  description = "GitHub repository (owner/name) whose workflows may deploy."
  type        = string
  default     = "KianRK/infrastructai"
}

variable "github_subjects" {
  description = <<-EOT
    Which workflow runs of the repository may log in to Azure, as the part of the OIDC
    subject after "repo:<owner>/<name>:". Keys are used in resource names.
  EOT
  type        = map(string)
  default = {
    main = "ref:refs/heads/main"
  }
}

variable "kubernetes_namespace" {
  description = "Namespace the application is deployed to."
  type        = string
  default     = "roadscan"
}

variable "serving_service_account" {
  description = "Kubernetes service account of the Ray pods (bound to the serving identity)."
  type        = string
  default     = "roadscan-serving"
}

variable "secrets_version" {
  description = <<-EOT
    Increase to generate a new demo password and a new session signing key. The values
    themselves never appear in the Terraform state.
  EOT
  type        = number
  default     = 1
}

# --- Cost ------------------------------------------------------------------------------

variable "budget_enabled" {
  description = "Create a monthly budget with e-mail alerts on the subscription."
  type        = bool
  default     = true
}

variable "budget_amount" {
  description = "Monthly budget in the subscription's billing currency."
  type        = number
  default     = 30
}

variable "budget_contact_emails" {
  description = "Recipients of the budget alerts. Set in terraform.tfvars (not committed)."
  type        = list(string)
  default     = []

  validation {
    condition     = !var.budget_enabled || length(var.budget_contact_emails) > 0
    error_message = "Set budget_contact_emails, or budget_enabled = false."
  }
}

variable "tags" {
  description = "Tags for all resources."
  type        = map(string)
  default     = {}
}
