terraform {
  required_version = ">= 1.7.0"

  backend "s3" {
    bucket               = "ahmadry98-polyai-tfstate-228281126655-us-east-1"
    key                  = "polyai/terraform.tfstate"
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
  region  = var.region
  profile = "default"
}

resource "aws_security_group" "polyai_dev" {
  name        = "${local.name_prefix}-sg"
  description = "Allow restricted SSH and public HTTP traffic"
  vpc_id      = var.env == "prod" ? aws_vpc.prod[0].id : null
  ingress {
    description = "SSH from my public IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["147.235.223.172/32"]
  }

  ingress {
    description = "HTTP from the internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-sg"
  })
}

resource "aws_key_pair" "polyai_dev" {
  key_name   = local.name_prefix
  public_key = file(pathexpand("~/.ssh/ahmadry98-polyai-dev.pub"))

  tags = merge(local.common_tags, {
    Name = local.name_prefix
  })
}

resource "aws_s3_bucket" "polyai_dev" {
  bucket = "${local.name_prefix}-228281126655-${var.region}"

  tags = merge(local.common_tags, {
    Name = local.name_prefix
  })
}

resource "aws_instance" "polyai_dev" {
  depends_on = [aws_s3_bucket.polyai_dev]

  ami                    = data.aws_ami.ubuntu.id
  instance_type          = "t2.nano"
  key_name               = aws_key_pair.polyai_dev.key_name
  subnet_id              = var.env == "prod" ? aws_subnet.prod_public[0].id : null
  vpc_security_group_ids = [aws_security_group.polyai_dev.id]
  tags = merge(local.common_tags, {
    DriftTest = "added-manually"
    Name      = local.name_prefix
  })
}

resource "aws_ebs_volume" "polyai_dev" {
  availability_zone = aws_instance.polyai_dev.availability_zone
  encrypted         = true
  size              = 5
  type              = "gp3"

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-data"
  })
}

resource "aws_volume_attachment" "polyai_dev" {
  device_name = "/dev/sdf"
  instance_id = aws_instance.polyai_dev.id
  volume_id   = aws_ebs_volume.polyai_dev.id
}