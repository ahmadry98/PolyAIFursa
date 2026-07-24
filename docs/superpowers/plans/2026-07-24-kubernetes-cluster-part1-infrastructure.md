# Kubernetes Cluster Part I Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the completed Terraform tutorial stack with a region-portable AWS VPC and a reusable local module that automatically provisions a kubeadm control plane and Auto Scaling Group workers.

**Architecture:** The root Terraform configuration retains the existing encrypted S3 backend, calls the public AWS VPC module for two public subnets, and passes the resulting network IDs into `modules/k8s-cluster`. The local module initializes Kubernetes and CRI-O v1.35 through cloud-init, stores a protected worker join command in SSM Parameter Store, and lets worker instances retrieve it through a narrow instance role.

**Tech Stack:** Terraform >=1.7, AWS provider, terraform-aws-modules/vpc/aws, EC2, IAM, SSM Parameter Store, Launch Templates, Auto Scaling, Ubuntu 24.04, CRI-O v1.35, Kubernetes v1.35, kubeadm.

---

## Scope Boundary

This plan implements Part I only. It does not install Calico or Argo CD and
does not create GitHub Actions workflows. A newly joined Node may remain
`NotReady` until Part II installs Calico; that is expected.

The existing manual Kubernetes cluster is out of scope and must remain running.

## Final File Map

```text
infra/tf/
├── .terraform.lock.hcl
├── data.tf
├── locals.tf
├── main.tf
├── outputs.tf
├── variables.tf
├── versions.tf
├── tfvars/
│   └── us-east-1.tfvars
└── modules/
    └── k8s-cluster/
        ├── main.tf
        ├── variables.tf
        ├── outputs.tf
        ├── control-plane-user-data.sh.tftpl
        └── worker-user-data.sh.tftpl
```

## Task 1: Safely retire the tutorial Terraform resources

**Files:**
- Read: `infra/tf/main.tf`
- Read: `infra/tf/dev.tfvars` (ignored local file)
- Read: `infra/tf/prod.tfvars` (ignored local file)
- Do not modify source files until both destruction plans are applied and verified.

- [ ] **Step 1: Confirm the old workspaces and current branch**

Run:

```bash
git branch --show-current
git status --short
terraform -chdir=infra/tf workspace list
```

Expected:

```text
task6
```

The working tree must contain no uncommitted infrastructure edits. The old
workspace list must contain `us-east-1.dev` and `eu-central-1.prod`.

- [ ] **Step 2: Review the dev destruction plan**

Run:

```bash
terraform -chdir=infra/tf workspace select us-east-1.dev
terraform -chdir=infra/tf plan \
  -destroy \
  -var-file="dev.tfvars" \
  -out="destroy-tutorial-dev.tfplan"
```

Expected: only the six tutorial-managed dev resources are marked for
destruction. The manually configured Kubernetes EC2 instance at
`34.203.11.243` must not appear.

- [ ] **Step 3: Apply the reviewed dev destruction plan**

Run only after reviewing every address:

```bash
terraform -chdir=infra/tf apply "destroy-tutorial-dev.tfplan"
terraform -chdir=infra/tf state list
```

Expected: `Resources: 0 added, 0 changed, 6 destroyed` and an empty dev state.

- [ ] **Step 4: Review the prod destruction plan**

Run:

```bash
terraform -chdir=infra/tf workspace select eu-central-1.prod
terraform -chdir=infra/tf plan \
  -destroy \
  -var-file="prod.tfvars" \
  -out="destroy-tutorial-prod.tfplan"
```

Expected: only the tutorial-managed prod VPC, EC2, EBS, key pair, S3 bucket,
security group, routing, and attachment resources are marked for destruction.
The manual Kubernetes cluster must not appear.

- [ ] **Step 5: Apply the reviewed prod destruction plan**

Run only after reviewing every address:

```bash
terraform -chdir=infra/tf apply "destroy-tutorial-prod.tfplan"
terraform -chdir=infra/tf state list
```

Expected: the prod state is empty.

- [ ] **Step 6: Remove the empty tutorial workspaces**

Run:

```bash
terraform -chdir=infra/tf workspace select default
terraform -chdir=infra/tf workspace delete us-east-1.dev
terraform -chdir=infra/tf workspace delete eu-central-1.prod
terraform -chdir=infra/tf workspace list
```

Expected: only `default` remains.

- [ ] **Step 7: Commit no changes**

This task changes remote infrastructure and state only. Do not create a Git
commit.

## Task 2: Replace the tutorial root interface

**Files:**
- Delete: `infra/tf/network.tf`
- Delete: `infra/tf/vpc_module.tf`
- Replace: `infra/tf/main.tf`
- Replace: `infra/tf/variables.tf`
- Replace: `infra/tf/data.tf`
- Replace: `infra/tf/locals.tf`
- Replace: `infra/tf/outputs.tf`
- Create: `infra/tf/versions.tf`
- Create: `infra/tf/tfvars/us-east-1.tfvars`
- Modify: `.gitignore`

- [ ] **Step 1: Generate a dedicated cluster SSH key**

Run:

```bash
test ! -e ~/.ssh/ahmadry98-polyai-k8s
test ! -e ~/.ssh/ahmadry98-polyai-k8s.pub
ssh-keygen \
  -t ed25519 \
  -f ~/.ssh/ahmadry98-polyai-k8s \
  -C "ahmadry98-polyai-k8s" \
  -N ""
chmod 600 ~/.ssh/ahmadry98-polyai-k8s
chmod 644 ~/.ssh/ahmadry98-polyai-k8s.pub
```

Expected: a new private/public key pair exists only under `~/.ssh`. Neither
file is copied into the repository. The existing manual cluster continues using
its separate `Ahmad-kube.pem` key.

- [ ] **Step 2: Confirm the administrator CIDR**

Run:

```bash
curl -fsS https://checkip.amazonaws.com
```

Expected: the returned address matches the `/32` used later in
`tfvars/us-east-1.tfvars`. If it differs, use the current address instead of
`147.235.223.172/32`.

- [ ] **Step 3: Allow non-secret regional tfvars**

Add this exception after the existing `*.tfvars` ignore rule:

```gitignore
!infra/tf/tfvars/
!infra/tf/tfvars/*.tfvars
```

The regional file contains no password, private key, token, or AWS credential.

- [ ] **Step 4: Create `versions.tf`**

```hcl
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
```

Do not set `profile = "default"`; local AWS configuration and GitHub OIDC both
work through the standard provider credential chain.

- [ ] **Step 5: Replace `variables.tf`**

```hcl
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
```

- [ ] **Step 6: Replace `data.tf`**

```hcl
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}
```

- [ ] **Step 7: Replace `locals.tf`**

```hcl
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
```

- [ ] **Step 8: Replace root `main.tf`**

```hcl
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.8.1"

  name = "${local.name_prefix}-vpc"
  cidr = var.vpc_cidr

  azs            = local.azs
  public_subnets = var.public_subnet_cidrs

  enable_nat_gateway     = false
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
```

- [ ] **Step 9: Replace root `outputs.tf`**

```hcl
output "vpc_id" {
  description = "ID of the cluster VPC"
  value       = module.vpc.vpc_id
}

output "public_subnet_ids" {
  description = "IDs of the two public subnets"
  value       = module.vpc.public_subnets
}

output "control_plane_public_ip" {
  description = "Public IPv4 address of the kubeadm control plane"
  value       = module.k8s_cluster.control_plane_public_ip
}

output "control_plane_private_ip" {
  description = "Private IPv4 address advertised by kubeadm"
  value       = module.k8s_cluster.control_plane_private_ip
}

output "control_plane_instance_id" {
  description = "EC2 instance ID of the control plane"
  value       = module.k8s_cluster.control_plane_instance_id
}

output "control_plane_security_group_id" {
  description = "Security group modified temporarily by the bootstrap workflow"
  value       = module.k8s_cluster.control_plane_security_group_id
}

output "worker_asg_name" {
  description = "Name of the worker Auto Scaling Group"
  value       = module.k8s_cluster.worker_asg_name
}

output "ssh_command" {
  description = "Example command for connecting to the control plane"
  value       = "ssh ubuntu@${module.k8s_cluster.control_plane_public_ip}"
}
```

- [ ] **Step 10: Create `tfvars/us-east-1.tfvars`**

```hcl
region = "us-east-1"

vpc_cidr = "10.0.0.0/16"
public_subnet_cidrs = [
  "10.0.1.0/24",
  "10.0.2.0/24",
]

pod_cidr                      = "192.168.0.0/16"
kubernetes_minor_version     = "v1.35"
control_plane_instance_type  = "t3.medium"
worker_instance_type         = "t3.medium"
worker_desired_capacity      = 1
admin_ssh_cidr               = "147.235.223.172/32"
application_s3_bucket        = "ahmad-polyai-images"
```

- [ ] **Step 11: Remove obsolete tutorial files**

Delete:

```text
infra/tf/network.tf
infra/tf/vpc_module.tf
```

The ignored local `dev.tfvars`, `prod.tfvars`, and old plan files are not
committed and may be archived locally after the old stacks are destroyed.

- [ ] **Step 12: Format and confirm the expected initial failure**

Run:

```bash
terraform fmt -recursive infra/tf
terraform -chdir=infra/tf validate
```

Expected: validation fails because `./modules/k8s-cluster` does not exist yet.
This verifies that the root module now depends on the planned local module.

- [ ] **Step 13: Commit the root interface**

```bash
git add .gitignore infra/tf
git commit -m "refactor: define Kubernetes cluster Terraform root"
```

Before committing, confirm no `.tfstate`, `.tfplan`, `.terraform/`, PEM, or
private-key file is staged.

## Task 3: Define the local k8s-cluster module interface

**Files:**
- Create: `infra/tf/modules/k8s-cluster/variables.tf`
- Create: `infra/tf/modules/k8s-cluster/outputs.tf`

- [ ] **Step 1: Create module `variables.tf`**

```hcl
variable "name_prefix" {
  description = "Prefix applied to cluster resource names"
  type        = string
}

variable "region" {
  description = "AWS region containing the cluster"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for cluster resources"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR permitted for internal cluster traffic"
  type        = string
}

variable "public_subnet_ids" {
  description = "Two public subnet IDs used by the control plane and workers"
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_ids) == 2
    error_message = "Exactly two public subnet IDs are required."
  }
}

variable "ubuntu_ami_id" {
  description = "Canonical Ubuntu 24.04 AMI ID for the selected region"
  type        = string
}

variable "kubernetes_minor_version" {
  description = "Kubernetes and CRI-O repository stream"
  type        = string
}

variable "pod_cidr" {
  description = "Kubernetes Pod network CIDR"
  type        = string
}

variable "control_plane_instance_type" {
  description = "EC2 type for the control plane"
  type        = string
}

variable "worker_instance_type" {
  description = "EC2 type for ASG workers"
  type        = string
}

variable "worker_desired_capacity" {
  description = "Desired ASG capacity from zero through three"
  type        = number
}

variable "admin_ssh_cidr" {
  description = "Administrator CIDR permitted to SSH to the control plane"
  type        = string
}

variable "ssh_public_key" {
  description = "OpenSSH public key registered in EC2"
  type        = string
  sensitive   = true
}

variable "application_s3_bucket" {
  description = "S3 bucket used by PolyAI workloads"
  type        = string
}

variable "tags" {
  description = "Tags applied to module resources"
  type        = map(string)
  default     = {}
}
```

- [ ] **Step 2: Create module `outputs.tf`**

```hcl
output "control_plane_public_ip" {
  description = "Control-plane public IPv4 address"
  value       = aws_instance.control_plane.public_ip
}

output "control_plane_private_ip" {
  description = "Control-plane private IPv4 address"
  value       = aws_instance.control_plane.private_ip
}

output "control_plane_instance_id" {
  description = "Control-plane EC2 instance ID"
  value       = aws_instance.control_plane.id
}

output "control_plane_security_group_id" {
  description = "Control-plane security group ID"
  value       = aws_security_group.control_plane.id
}

output "worker_asg_name" {
  description = "Worker Auto Scaling Group name"
  value       = aws_autoscaling_group.workers.name
}

output "join_parameter_name" {
  description = "SSM parameter name containing the protected join command"
  value       = aws_ssm_parameter.kubeadm_join.name
}
```

- [ ] **Step 3: Run validation to verify the next expected failure**

Run:

```bash
terraform fmt -recursive infra/tf
terraform -chdir=infra/tf init
terraform -chdir=infra/tf validate
```

Expected: module outputs fail because module resources are not defined yet.

- [ ] **Step 4: Commit the module contract**

```bash
git add infra/tf/modules/k8s-cluster/variables.tf \
  infra/tf/modules/k8s-cluster/outputs.tf
git commit -m "feat: define Kubernetes cluster module interface"
```

## Task 4: Add control-plane and worker cloud-init templates

**Files:**
- Create: `infra/tf/modules/k8s-cluster/control-plane-user-data.sh.tftpl`
- Create: `infra/tf/modules/k8s-cluster/worker-user-data.sh.tftpl`

- [ ] **Step 1: Create the control-plane template**

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

exec > >(tee -a /var/log/polyai-control-plane-bootstrap.log) 2>&1

export DEBIAN_FRONTEND=noninteractive
KUBERNETES_VERSION="${kubernetes_minor_version}"
CRIO_VERSION="${kubernetes_minor_version}"

swapoff -a
sed -ri '/\sswap\s/s/^#?/#/' /etc/fstab

cat >/etc/modules-load.d/kubernetes.conf <<'MODULES'
overlay
br_netfilter
MODULES

modprobe overlay
modprobe br_netfilter

cat >/etc/sysctl.d/99-kubernetes-cri.conf <<'SYSCTL'
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
SYSCTL

sysctl --system

install -m 0755 -d /etc/apt/keyrings
apt-get update
apt-get install -y ca-certificates curl gpg awscli

curl -fsSL "https://pkgs.k8s.io/core:/stable:/$${KUBERNETES_VERSION}/deb/Release.key" \
  | gpg --dearmor --yes -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/$${KUBERNETES_VERSION}/deb/ /" \
  >/etc/apt/sources.list.d/kubernetes.list

curl -fsSL "https://download.opensuse.org/repositories/isv:/cri-o:/stable:/$${CRIO_VERSION}/deb/Release.key" \
  | gpg --dearmor --yes -o /etc/apt/keyrings/cri-o-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/cri-o-apt-keyring.gpg] https://download.opensuse.org/repositories/isv:/cri-o:/stable:/$${CRIO_VERSION}/deb/ /" \
  >/etc/apt/sources.list.d/cri-o.list

apt-get update
apt-get install -y cri-o kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

systemctl enable --now crio
systemctl enable kubelet

TOKEN=$(curl -fsS -X PUT \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" \
  http://169.254.169.254/latest/api/token)
PRIVATE_IP=$(curl -fsS \
  -H "X-aws-ec2-metadata-token: $${TOKEN}" \
  http://169.254.169.254/latest/meta-data/local-ipv4)

if [[ ! -f /etc/kubernetes/admin.conf ]]; then
  kubeadm init \
    --apiserver-advertise-address="$${PRIVATE_IP}" \
    --pod-network-cidr="${pod_cidr}" \
    --cri-socket=unix:///var/run/crio/crio.sock
fi

install -d -m 0700 -o ubuntu -g ubuntu /home/ubuntu/.kube
install -m 0600 -o ubuntu -g ubuntu \
  /etc/kubernetes/admin.conf \
  /home/ubuntu/.kube/config

JOIN_COMMAND=$(kubeadm token create --ttl 0 --print-join-command)
JOIN_COMMAND="$${JOIN_COMMAND} --cri-socket unix:///var/run/crio/crio.sock"

aws ssm put-parameter \
  --region "${region}" \
  --name "${join_parameter_name}" \
  --type SecureString \
  --value "$${JOIN_COMMAND}" \
  --overwrite >/dev/null

touch /var/lib/polyai-control-plane-ready
```

- [ ] **Step 2: Create the worker template**

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

exec > >(tee -a /var/log/polyai-worker-bootstrap.log) 2>&1

export DEBIAN_FRONTEND=noninteractive
KUBERNETES_VERSION="${kubernetes_minor_version}"
CRIO_VERSION="${kubernetes_minor_version}"

swapoff -a
sed -ri '/\sswap\s/s/^#?/#/' /etc/fstab

cat >/etc/modules-load.d/kubernetes.conf <<'MODULES'
overlay
br_netfilter
MODULES

modprobe overlay
modprobe br_netfilter

cat >/etc/sysctl.d/99-kubernetes-cri.conf <<'SYSCTL'
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
SYSCTL

sysctl --system

install -m 0755 -d /etc/apt/keyrings
apt-get update
apt-get install -y ca-certificates curl gpg awscli

curl -fsSL "https://pkgs.k8s.io/core:/stable:/$${KUBERNETES_VERSION}/deb/Release.key" \
  | gpg --dearmor --yes -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/$${KUBERNETES_VERSION}/deb/ /" \
  >/etc/apt/sources.list.d/kubernetes.list

curl -fsSL "https://download.opensuse.org/repositories/isv:/cri-o:/stable:/$${CRIO_VERSION}/deb/Release.key" \
  | gpg --dearmor --yes -o /etc/apt/keyrings/cri-o-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/cri-o-apt-keyring.gpg] https://download.opensuse.org/repositories/isv:/cri-o:/stable:/$${CRIO_VERSION}/deb/ /" \
  >/etc/apt/sources.list.d/cri-o.list

apt-get update
apt-get install -y cri-o kubelet kubeadm
apt-mark hold kubelet kubeadm

systemctl enable --now crio
systemctl enable kubelet

if [[ -f /etc/kubernetes/kubelet.conf ]]; then
  exit 0
fi

JOIN_COMMAND=""
for attempt in $(seq 1 120); do
  JOIN_COMMAND=$(aws ssm get-parameter \
    --region "${region}" \
    --name "${join_parameter_name}" \
    --with-decryption \
    --query 'Parameter.Value' \
    --output text 2>/dev/null || true)

  if [[ "$${JOIN_COMMAND}" == kubeadm\ join* ]]; then
    break
  fi

  JOIN_COMMAND=""
  sleep 15
done

if [[ -z "$${JOIN_COMMAND}" ]]; then
  echo "Timed out waiting for a valid kubeadm join command" >&2
  exit 1
fi

read -r -a JOIN_ARGS <<<"$${JOIN_COMMAND}"
"$${JOIN_ARGS[@]}"

touch /var/lib/polyai-worker-ready
```

- [ ] **Step 3: Syntax-check both templates as rendered shell**

The templates contain Terraform substitutions, so copy rendered output from
`terraform console` after Task 5 or use `templatefile` through a temporary
output. At this stage, check all literal shell portions:

```bash
bash -n infra/tf/modules/k8s-cluster/control-plane-user-data.sh.tftpl
bash -n infra/tf/modules/k8s-cluster/worker-user-data.sh.tftpl
```

Expected: both exit zero.

- [ ] **Step 4: Commit the templates**

```bash
git add infra/tf/modules/k8s-cluster/*.sh.tftpl
git commit -m "feat: add kubeadm node bootstrap templates"
```

## Task 5: Implement the local k8s-cluster module

**Files:**
- Create: `infra/tf/modules/k8s-cluster/main.tf`

- [ ] **Step 1: Create module locals, key pair, and SSM parameter**

Start `main.tf` with:

```hcl
locals {
  join_parameter_name = "/polyai/${var.name_prefix}/kubeadm-join"
  worker_min_size      = var.worker_desired_capacity == 0 ? 0 : 1
}

resource "aws_key_pair" "cluster" {
  key_name   = "${var.name_prefix}-key"
  public_key = var.ssh_public_key

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-key"
  })
}

resource "aws_ssm_parameter" "kubeadm_join" {
  name        = local.join_parameter_name
  description = "Encrypted kubeadm join command written by the control plane"
  type        = "SecureString"
  value       = "pending-control-plane-initialization"

  lifecycle {
    ignore_changes = [value]
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-kubeadm-join"
  })
}
```

- [ ] **Step 2: Add IAM roles and policies**

Append:

```hcl
data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "control_plane" {
  name               = "${var.name_prefix}-control-plane"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "control_plane_required" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
    "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
  ])

  role       = aws_iam_role.control_plane.name
  policy_arn = each.value
}

data "aws_iam_policy_document" "control_plane_ssm" {
  statement {
    sid       = "WriteJoinParameter"
    effect    = "Allow"
    actions   = ["ssm:PutParameter"]
    resources = [aws_ssm_parameter.kubeadm_join.arn]
  }
}

resource "aws_iam_role_policy" "control_plane_ssm" {
  name   = "write-kubeadm-join"
  role   = aws_iam_role.control_plane.id
  policy = data.aws_iam_policy_document.control_plane_ssm.json
}

resource "aws_iam_instance_profile" "control_plane" {
  name = "${var.name_prefix}-control-plane"
  role = aws_iam_role.control_plane.name
}

resource "aws_iam_role" "worker" {
  name               = "${var.name_prefix}-worker"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "worker_ecr" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

data "aws_iam_policy_document" "worker_runtime" {
  statement {
    sid       = "ReadJoinParameter"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.kubeadm_join.arn]
  }

  statement {
    sid    = "UseApplicationBucket"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["arn:aws:s3:::${var.application_s3_bucket}/*"]
  }

  statement {
    sid       = "ListApplicationBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.application_s3_bucket}"]
  }

  statement {
    sid    = "InvokeBedrockModels"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "worker_runtime" {
  name   = "polyai-worker-runtime"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_runtime.json
}

resource "aws_iam_instance_profile" "worker" {
  name = "${var.name_prefix}-worker"
  role = aws_iam_role.worker.name
}
```

- [ ] **Step 3: Add security groups and rules**

Append:

```hcl
resource "aws_security_group" "control_plane" {
  name        = "${var.name_prefix}-control-plane"
  description = "Kubernetes control-plane traffic"
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-control-plane"
  })
}

resource "aws_vpc_security_group_ingress_rule" "control_plane_ssh" {
  security_group_id = aws_security_group.control_plane.id
  description       = "SSH from the administrator CIDR"
  cidr_ipv4         = var.admin_ssh_cidr
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "control_plane_internal" {
  security_group_id = aws_security_group.control_plane.id
  description       = "All intra-VPC cluster traffic"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_egress_rule" "control_plane_all" {
  security_group_id = aws_security_group.control_plane.id
  description       = "Outbound package, registry, and AWS API access"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "worker" {
  name        = "${var.name_prefix}-worker"
  description = "Kubernetes worker traffic"
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-worker"
  })
}

resource "aws_vpc_security_group_ingress_rule" "worker_internal" {
  security_group_id = aws_security_group.worker.id
  description       = "All intra-VPC cluster traffic"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_egress_rule" "worker_all" {
  security_group_id = aws_security_group.worker.id
  description       = "Outbound package, registry, and AWS API access"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
```

- [ ] **Step 4: Add the control-plane instance**

Append:

```hcl
resource "aws_instance" "control_plane" {
  ami                         = var.ubuntu_ami_id
  instance_type               = var.control_plane_instance_type
  subnet_id                   = var.public_subnet_ids[0]
  associate_public_ip_address = true
  key_name                    = aws_key_pair.cluster.key_name
  vpc_security_group_ids      = [aws_security_group.control_plane.id]
  iam_instance_profile        = aws_iam_instance_profile.control_plane.name

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    encrypted   = true
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = templatefile(
    "${path.module}/control-plane-user-data.sh.tftpl",
    {
      kubernetes_minor_version = var.kubernetes_minor_version
      pod_cidr                 = var.pod_cidr
      region                   = var.region
      join_parameter_name      = aws_ssm_parameter.kubeadm_join.name
    }
  )

  user_data_replace_on_change = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-control-plane"
    Role = "control-plane"
  })

  depends_on = [
    aws_iam_role_policy.control_plane_ssm,
    aws_iam_role_policy_attachment.control_plane_required,
  ]
}
```

- [ ] **Step 5: Add the worker launch template and ASG**

Append:

```hcl
resource "aws_launch_template" "worker" {
  name_prefix   = "${var.name_prefix}-worker-"
  image_id      = var.ubuntu_ami_id
  instance_type = var.worker_instance_type
  key_name      = aws_key_pair.cluster.key_name

  iam_instance_profile {
    name = aws_iam_instance_profile.worker.name
  }

  network_interfaces {
    associate_public_ip_address = true
    delete_on_termination       = true
    device_index                = 0
    security_groups             = [aws_security_group.worker.id]
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  block_device_mappings {
    device_name = "/dev/sda1"

    ebs {
      encrypted             = true
      volume_size           = 20
      volume_type           = "gp3"
      delete_on_termination = true
    }
  }

  user_data = base64encode(templatefile(
    "${path.module}/worker-user-data.sh.tftpl",
    {
      kubernetes_minor_version = var.kubernetes_minor_version
      region                   = var.region
      join_parameter_name      = aws_ssm_parameter.kubeadm_join.name
    }
  ))

  tag_specifications {
    resource_type = "instance"

    tags = merge(var.tags, {
      Name = "${var.name_prefix}-worker"
      Role = "worker"
    })
  }

  tag_specifications {
    resource_type = "volume"
    tags          = var.tags
  }

  depends_on = [
    aws_iam_role_policy.worker_runtime,
    aws_iam_role_policy_attachment.worker_ecr,
  ]
}

resource "aws_autoscaling_group" "workers" {
  name                = "${var.name_prefix}-workers"
  min_size            = local.worker_min_size
  max_size            = 3
  desired_capacity    = var.worker_desired_capacity
  vpc_zone_identifier = var.public_subnet_ids
  health_check_type   = "EC2"

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }

  dynamic "tag" {
    for_each = merge(var.tags, {
      Name = "${var.name_prefix}-worker"
      Role = "worker"
    })

    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }
}
```

- [ ] **Step 6: Format and validate**

Provide the public key through the environment:

```bash
export TF_VAR_ssh_public_key="$(cat ~/.ssh/ahmadry98-polyai-k8s.pub)"
terraform fmt -recursive infra/tf
terraform -chdir=infra/tf init -reconfigure
terraform -chdir=infra/tf validate
```

Expected:

```text
Success! The configuration is valid.
```

- [ ] **Step 7: Inspect rendered user data**

Run:

```bash
terraform -chdir=infra/tf console \
  -var-file="tfvars/us-east-1.tfvars"
```

Evaluate the two `templatefile(...)` expressions from `main.tf`, confirm they
render without interpolation errors, then exit with `Ctrl+D`.

- [ ] **Step 8: Commit the module implementation**

```bash
git add infra/tf/modules/k8s-cluster/main.tf
git commit -m "feat: provision kubeadm control plane and workers"
```

## Task 6: Create and review the regional cluster plan

**Files:**
- No source changes expected.

- [ ] **Step 1: Create the regional workspace**

Run:

```bash
terraform -chdir=infra/tf workspace select default
terraform -chdir=infra/tf workspace new us-east-1
terraform -chdir=infra/tf workspace show
```

Expected:

```text
us-east-1
```

- [ ] **Step 2: Run static checks**

```bash
terraform fmt -check -recursive infra/tf
terraform -chdir=infra/tf validate
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 3: Save the plan**

```bash
export TF_VAR_ssh_public_key="$(cat ~/.ssh/ahmadry98-polyai-k8s.pub)"
terraform -chdir=infra/tf plan \
  -var-file="tfvars/us-east-1.tfvars" \
  -out="create-kubernetes-cluster.tfplan"
```

Expected additions include:

- VPC and two public subnets in different AZs.
- Internet gateway and public routing.
- Control-plane EC2 with `t3.medium` and 20 GiB encrypted root storage.
- Required control-plane IAM policies.
- Worker launch template and ASG with min 1, max 3, desired 1.
- Encrypted SSM parameter.

Expected: no existing manual-cluster instance is changed or destroyed.

- [ ] **Step 4: Produce a human-readable plan artifact**

```bash
terraform -chdir=infra/tf show \
  -no-color \
  "create-kubernetes-cluster.tfplan" \
  > /tmp/polyai-k8s-plan.txt
```

Review:

```bash
rg -n "will be destroyed|must be replaced|0.0.0.0/0|AmazonEKSClusterPolicy|desired_capacity|min_size|max_size" \
  /tmp/polyai-k8s-plan.txt
```

Expected: no destruction or replacement. Public `0.0.0.0/0` appears only for
egress and public subnet routing, not permanent SSH ingress.

- [ ] **Step 5: Stop for explicit apply approval**

Do not apply until the user reviews the saved plan summary and confirms the AWS
cost-bearing creation.

## Task 7: Apply and verify Part I

**Files:**
- No source changes expected.

- [ ] **Step 1: Apply the exact reviewed plan**

```bash
terraform -chdir=infra/tf apply "create-kubernetes-cluster.tfplan"
```

Expected: Terraform creates the network, control plane, launch template, and
one worker without errors.

- [ ] **Step 2: Record non-secret outputs**

```bash
terraform -chdir=infra/tf output
terraform -chdir=infra/tf state list
```

Expected: public/private control-plane IPs, instance ID, security-group ID, ASG
name, VPC ID, and two subnet IDs. No join command appears.

- [ ] **Step 3: Wait for control-plane cloud-init**

Use the private key corresponding to the supplied public key:

```bash
CONTROL_PLANE_IP=$(terraform -chdir=infra/tf output -raw control_plane_public_ip)
ssh -i ~/.ssh/ahmadry98-polyai-k8s \
  -o StrictHostKeyChecking=accept-new \
  "ubuntu@${CONTROL_PLANE_IP}" \
  'cloud-init status --wait && test -f /var/lib/polyai-control-plane-ready'
```

Expected: cloud-init reports `status: done`, and the readiness marker exists.

- [ ] **Step 4: Verify kubeadm and the protected parameter**

```bash
ssh -i ~/.ssh/ahmadry98-polyai-k8s "ubuntu@${CONTROL_PLANE_IP}" \
  'kubectl get nodes -o wide; sudo systemctl is-active crio kubelet'

aws ssm describe-parameters \
  --region us-east-1 \
  --parameter-filters \
    "Key=Name,Option=Equals,Values=/polyai/ahmadry98-polyai-k8s-us-east-1/kubeadm-join" \
  --query 'Parameters[0].{Name:Name,Type:Type}' \
  --output table
```

Expected: CRI-O and kubelet are active; the parameter type is `SecureString`.
Do not retrieve or print its value.

- [ ] **Step 5: Verify the worker joined**

```bash
ssh -i ~/.ssh/ahmadry98-polyai-k8s "ubuntu@${CONTROL_PLANE_IP}" \
  'kubectl get nodes -o wide'
```

Expected: one control-plane Node and one worker Node. They may be `NotReady`
until Calico is installed in Part II.

- [ ] **Step 6: Run a zero-change Terraform plan**

```bash
export TF_VAR_ssh_public_key="$(cat ~/.ssh/ahmadry98-polyai-k8s.pub)"
terraform -chdir=infra/tf plan \
  -var-file="tfvars/us-east-1.tfvars"
```

Expected:

```text
No changes. Your infrastructure matches the configuration.
```

- [ ] **Step 7: Commit any verification documentation**

If implementation revealed no source corrections, no commit is needed. If
commands or operational notes were corrected, stage only those documentation
files and commit:

```bash
git commit -m "docs: add Kubernetes infrastructure verification"
```

## Part I Completion Checklist

- [ ] Old tutorial dev resources destroyed from their reviewed state.
- [ ] Old tutorial prod resources destroyed from their reviewed state.
- [ ] Existing manual Kubernetes cluster still running.
- [ ] Regional workspace is `us-east-1`.
- [ ] VPC has two public subnets in different Availability Zones.
- [ ] Control plane is Ubuntu, `t3.medium`, and has encrypted 20 GiB storage.
- [ ] Control plane initialized automatically with Kubernetes/CRI-O v1.35.
- [ ] Required control-plane IAM policies are attached.
- [ ] Worker ASG has max 3 and conditional idle minimum behavior.
- [ ] Worker read the encrypted SSM join command and joined automatically.
- [ ] Terraform reports no changes after apply.
- [ ] No sensitive value exists in Git, Terraform output, or plan artifacts.
- [ ] Calico and Argo CD remain unimplemented until Part II.
