locals {
  name_prefix = "ahmadry98-polyai-${var.env}"

  common_tags = {
    Env       = var.env
    ManagedBy = "Terraform"
    Owner     = "ahmadry98"
  }
}
