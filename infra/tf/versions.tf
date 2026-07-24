terraform {
  required_version = ">= 1.7.0"

  backend "s3" {
    bucket               = "ahmadry98-polyai-tfstate-228281126655-us-east-1"
    key                  = "polyai-k8s/terraform.tfstate"
    region               = "us-east-1"
    encrypt              = true
    use_lockfile         = true
    workspace_key_prefix = "workspaces"
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.55"
    }
  }
}

provider "aws" {
  region = var.region
}
