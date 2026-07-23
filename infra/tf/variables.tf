
variable "env" {
  description = "Deployment environment"
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "The environment must be dev or prod."
  }
}

variable "region" {
  description = "AWS region where resources are deployed"
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.region))
    error_message = "The AWS region must look like us-east-1."
  }
}


