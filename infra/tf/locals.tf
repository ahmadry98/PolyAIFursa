locals {
  name_prefix = "ahmadry98-polyai-k8s-${terraform.workspace}"
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)

  common_tags = {
    Project   = "PolyAIFursa"
    ManagedBy = "Terraform"
    Owner     = "ahmadry98"
    Workspace = terraform.workspace
  }
}