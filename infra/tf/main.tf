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

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"

  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "alert_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
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
  enable_cluster_autoscaler   = var.enable_cluster_autoscaler
  admin_ssh_cidr              = var.admin_ssh_cidr
  ssh_public_key              = var.ssh_public_key
  application_s3_bucket       = var.application_s3_bucket
  alert_sns_topic_arn         = aws_sns_topic.alerts.arn
  tags                        = local.common_tags
}

module "ingress" {
  source = "./modules/ingress"

  domain_name              = var.domain_name
  hosted_zone_id           = data.aws_route53_zone.shared.zone_id
  http_node_port           = var.ingress_http_node_port
  name_prefix              = local.name_prefix
  public_hostnames         = local.public_hostnames
  public_subnet_ids        = module.vpc.public_subnets
  tags                     = local.common_tags
  vpc_id                   = module.vpc.vpc_id
  worker_asg_name          = module.k8s_cluster.worker_asg_name
  worker_security_group_id = module.k8s_cluster.worker_security_group_id
}
