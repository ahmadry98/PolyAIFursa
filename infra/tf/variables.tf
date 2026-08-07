variable "region" {
  description = "AWS region where the Kubernetes cluster is provisioned"
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.region))
    error_message = "The region must look like us-east-1."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR for the cluster VPC"
  type        = string
}

variable "public_subnet_cidrs" {
  description = "Two public subnet CIDRs in separate Availability Zones"
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_cidrs) == 2
    error_message = "Exactly two public subnet CIDRs are required."
  }
}

variable "pod_cidr" {
  description = "Kubernetes Pod network CIDR passed to kubeadm and Calico"
  type        = string
  default     = "192.168.0.0/16"
}

variable "kubernetes_minor_version" {
  description = "Pinned Kubernetes and CRI-O minor repository stream"
  type        = string
  default     = "v1.35"
}

variable "control_plane_instance_type" {
  description = "EC2 instance type for the kubeadm control plane"
  type        = string
  default     = "t3.medium"
}

variable "worker_instance_type" {
  description = "EC2 instance type used by the worker launch template"
  type        = string
  default     = "t3.medium"
}

variable "worker_desired_capacity" {
  description = "Desired number of worker instances; zero enables idle mode"
  type        = number
  default     = 1

  validation {
    condition     = var.worker_desired_capacity >= 0 && var.worker_desired_capacity <= 3
    error_message = "Worker desired capacity must be between 0 and 3."
  }
}

variable "admin_ssh_cidr" {
  description = "Administrator IPv4 CIDR allowed to SSH to the control plane"
  type        = string

  validation {
    condition     = can(cidrhost(var.admin_ssh_cidr, 0))
    error_message = "admin_ssh_cidr must be a valid IPv4 CIDR."
  }
}

variable "ssh_public_key" {
  description = "OpenSSH public key registered as the cluster EC2 key pair"
  type        = string
  sensitive   = true

  validation {
    condition     = startswith(var.ssh_public_key, "ssh-")
    error_message = "ssh_public_key must be an OpenSSH public key."
  }
}

variable "application_s3_bucket" {
  description = "Existing S3 bucket used by PolyAI workloads"
  type        = string
  default     = "ahmad-polyai-images"
}

variable "alert_email" {
  description = "Email address subscribed to infrastructure and application alerts"
  type        = string

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "domain_name" {
  description = "Existing public Route 53 hosted zone used for cluster endpoints"
  type        = string
  default     = "fursa.click"
}

variable "enable_cluster_autoscaler" {
  description = "Whether to configure the worker ASG for the optional Cluster Autoscaler"
  type        = bool
  default     = false
}

variable "ingress_http_node_port" {
  description = "Fixed ingress-nginx HTTP NodePort targeted by the ALB"
  type        = number
  default     = 30080

  validation {
    condition     = var.ingress_http_node_port >= 30000 && var.ingress_http_node_port <= 32767
    error_message = "ingress_http_node_port must be within the Kubernetes NodePort range."
  }
}
