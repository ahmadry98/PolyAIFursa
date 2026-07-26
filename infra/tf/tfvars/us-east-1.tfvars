region = "us-east-1"

vpc_cidr = "10.0.0.0/16"
public_subnet_cidrs = [
  "10.0.1.0/24",
  "10.0.2.0/24",
]

pod_cidr                    = "192.168.0.0/16"
kubernetes_minor_version    = "v1.35"
control_plane_instance_type = "t3.medium"
worker_instance_type        = "t3.medium"
worker_desired_capacity     = 1
admin_ssh_cidr              = "147.235.223.172/32"
application_s3_bucket       = "ahmad-polyai-images"
