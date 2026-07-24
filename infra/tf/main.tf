module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.8.1"

  name = "${local.name_prefix}-vpc"
  cidr = var.vpc_cidr

  azs            = local.azs
  public_subnets = var.public_subnet_cidrs

  enable_nat_gateway      = false
  map_public_ip_on_launch = true

  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = local.common_tags
}

module "k8s_cluster" {
  source = "./modules/k8s-cluster"

  name_prefix                 = local.name_prefix
  region                      = var.region
  vpc_id                      = module.vpc.vpc_id
  vpc_cidr                    = var.vpc_cidr
  public_subnet_ids           = module.vpc.public_subnets
  ubuntu_ami_id               = data.aws_ami.ubuntu.id
  kubernetes_minor_version    = var.kubernetes_minor_version
  pod_cidr                    = var.pod_cidr
  control_plane_instance_type = var.control_plane_instance_type
  worker_instance_type        = var.worker_instance_type
  worker_desired_capacity     = var.worker_desired_capacity
  admin_ssh_cidr              = var.admin_ssh_cidr
  ssh_public_key              = var.ssh_public_key
  application_s3_bucket       = var.application_s3_bucket
  tags                        = local.common_tags
}