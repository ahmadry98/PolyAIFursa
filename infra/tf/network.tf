resource "aws_vpc" "prod" {
  count = var.env == "prod" ? 1 : 0

  cidr_block           = "10.20.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-vpc"
  })
}

resource "aws_internet_gateway" "prod" {
  count = var.env == "prod" ? 1 : 0

  vpc_id = aws_vpc.prod[0].id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-igw"
  })
}

resource "aws_subnet" "prod_public" {
  count = var.env == "prod" ? 1 : 0

  availability_zone       = "${var.region}a"
  cidr_block              = "10.20.1.0/24"
  map_public_ip_on_launch = true
  vpc_id                  = aws_vpc.prod[0].id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-public-subnet"
  })
}

resource "aws_route_table" "prod_public" {
  count = var.env == "prod" ? 1 : 0

  vpc_id = aws_vpc.prod[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.prod[0].id
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-public-rt"
  })
}

resource "aws_route_table_association" "prod_public" {
  count = var.env == "prod" ? 1 : 0

  route_table_id = aws_route_table.prod_public[0].id
  subnet_id      = aws_subnet.prod_public[0].id
}
