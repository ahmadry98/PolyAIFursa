locals {
  name_prefix = "ahmadry98-polyai-k8s-${terraform.workspace}"
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)

  public_hostnames = {
    argocd        = "argocd.${var.domain_name}"
    dev_agent     = "api-dev.${var.domain_name}"
    dev_frontend  = "dev.${var.domain_name}"
    grafana       = "grafana.${var.domain_name}"
    prod_agent    = "api.${var.domain_name}"
    prod_frontend = "app.${var.domain_name}"
    prometheus    = "prometheus.${var.domain_name}"
  }

  common_tags = {
    Project   = "PolyAIFursa"
    ManagedBy = "Terraform"
    Owner     = "ahmadry98"
    Workspace = terraform.workspace
  }
}
