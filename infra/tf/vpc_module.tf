module "polyai_service_vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.8.1"

  count = 0

  name = "${local.name_prefix}-module-vpc"
  cidr = "10.30.0.0/16"

  azs = slice(data.aws_availability_zones.available.names, 0, 2)

  private_subnets = [
    "10.30.1.0/24",
    "10.30.2.0/24",
  ]

  public_subnets = [
    "10.30.101.0/24",
    "10.30.102.0/24",
  ]

  enable_nat_gateway = false

  tags = local.common_tags
}
