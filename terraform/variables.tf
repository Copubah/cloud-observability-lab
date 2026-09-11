variable "aws_region" {
  type    = string
  default = "us-east-1"
}
variable "project_name" {
  type    = string
  default = "cloud-observability-lab"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.project_name))
    error_message = "Use 3-24 lowercase letters, digits or hyphens, starting with a letter."
  }
}
variable "environment" {
  type    = string
  default = "demo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,7}$", var.environment))
    error_message = "Use 2-8 lowercase letters, digits or hyphens."
  }
}
variable "allowed_client_cidr" {
  description = "Operator public IPv4 CIDR. Never defaults to internet-wide access."
  type        = string
  validation {
    condition     = can(cidrnetmask(var.allowed_client_cidr)) && try(tonumber(split("/", var.allowed_client_cidr)[1]) >= 24, false)
    error_message = "Supply an IPv4 CIDR with prefix /24 or narrower, preferably your public /32."
  }
}
variable "deploy_app" {
  description = "False creates only ECR repositories for image publication; true creates the full stack."
  type        = bool
  default     = false
}
variable "app_digest" {
  type    = string
  default = ""
  validation {
    condition     = var.app_digest == "" || can(regex("^sha256:[a-f0-9]{64}$", var.app_digest))
    error_message = "Use a sha256 image digest."
  }
}
variable "collector_digest" {
  type    = string
  default = ""
  validation {
    condition     = var.collector_digest == "" || can(regex("^sha256:[a-f0-9]{64}$", var.collector_digest))
    error_message = "Use a sha256 image digest."
  }
}
variable "simulate_db_latency" {
  type    = bool
  default = false
}
variable "simulate_errors" {
  type    = bool
  default = false
}
