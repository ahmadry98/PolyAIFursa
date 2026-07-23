# Kubernetes Cluster Provisioning as Code — Design

Date: 2026-07-23

Branch: `task6`

## Objective

Provision one self-managed Kubernetes cluster on AWS with Terraform and deploy
the PolyAI stack through Argo CD. The cluster hosts both development and
production workloads, separated by the `dev` and `prod` namespaces.

The existing manually configured cluster remains available until the new cluster
has passed the complete destroy-and-recreate test. It is not managed or retired
by this work.

## Scope

This design covers:

- A region-portable Terraform configuration, provisioned only in `us-east-1`.
- A VPC with two public subnets in separate Availability Zones.
- One automatically initialized kubeadm control plane.
- Worker instances managed by an Auto Scaling Group.
- Automatic worker joining through an encrypted SSM parameter.
- Manual Calico and Argo CD validation followed by workflow automation.
- Argo CD Applications for the four containerized PolyAI microservices.
- GitHub Actions workflows for cluster provisioning/bootstrap and GitOps image
  promotion.
- Safe migration away from the earlier Terraform tutorial resources.

This design does not cover:

- A highly available Kubernetes control plane.
- Automatic stale-Node cleanup during ASG scale-down.
- Retiring the existing manual cluster before the new cluster is verified.
- Containerizing or deploying `observability-mcp`, which currently has no
  Dockerfile or Kubernetes manifest.

## Decisions

| Area | Decision |
|---|---|
| AWS region | Provision only `us-east-1` |
| Terraform workspace | One regional workspace named `us-east-1` |
| Environments | One cluster with `dev` and `prod` namespaces |
| AWS workflow authentication | GitHub OIDC and a dedicated IAM role |
| Bootstrap access | SSH with a temporary GitHub-runner `/32` ingress rule |
| Kubernetes version | Kubernetes `v1.35` repository |
| Container runtime | CRI-O `v1.35` repository |
| Operating system | Canonical Ubuntu 24.04, discovered per region |
| Worker joining | Encrypted SSM SecureString containing `kubeadm join` |
| Worker token | Non-expiring, protected by narrowly scoped IAM |
| Scale-down Node cleanup | Manual `drain` and `delete node` |
| Dev delivery | Argo CD automatic sync from `dev` |
| Prod delivery | Argo CD manual sync from `main` |

## State and Migration

The existing `infra/tf` configuration is the completed Terraform tutorial. It
manages unrelated EC2, EBS, S3, security-group, key-pair, and networking
resources in the `us-east-1.dev` and `eu-central-1.prod` workspaces.

Before changing the root Terraform configuration:

1. Select each tutorial workspace.
2. create and review a saved destruction plan using its matching `.tfvars`.
3. Apply only the reviewed plan.
4. Verify that the managed AWS resources no longer exist.
5. Remove the obsolete tutorial workspaces after their states are empty.
6. Create the new regional workspace `us-east-1`.

The existing encrypted S3 backend and native S3 lock file are retained. The
GitHub OIDC provider and GitHub provisioning role are bootstrap prerequisites
outside the destroyable cluster state, allowing GitHub to recreate the cluster
after `terraform destroy`.

## Terraform Structure

```text
infra/tf/
├── tfvars/
│   └── us-east-1.tfvars
├── modules/
│   └── k8s-cluster/
│       ├── main.tf
│       ├── variables.tf
│       ├── outputs.tf
│       ├── control-plane-user-data.sh.tftpl
│       └── worker-user-data.sh.tftpl
├── main.tf
├── outputs.tf
├── variables.tf
└── versions.tf
```

The root module calls:

1. `terraform-aws-modules/vpc/aws` to create the VPC, Internet gateway,
   routing, and two public subnets.
2. The local `modules/k8s-cluster` module to create cluster compute, IAM,
   security groups, SSM parameter, launch template, and ASG.

### Root Inputs

The regional `.tfvars` supplies:

- Region and VPC CIDR.
- Two public-subnet CIDRs.
- Kubernetes pod CIDR.
- Control-plane and worker instance types.
- Worker desired capacity.
- Admin SSH CIDR.
- SSH public key.
- S3 bucket and Bedrock permissions required by PolyAI workloads.

Secrets and private keys are not stored in `.tfvars` committed to Git.
The SSH public-key input may be supplied locally or derived from the
`CLUSTER_SSH_PRIVATE_KEY` secret by the provisioning workflow.

## AWS Network

Initial network values:

```text
VPC CIDR: 10.0.0.0/16
Pod CIDR: 192.168.0.0/16
```

The VPC module places two public subnets in the first two available Availability
Zones. The control plane runs in the first subnet. The worker ASG spans both
subnets.

Instances receive public IPv4 addresses because the assignment uses public
subnets without a NAT gateway, and nodes must download OS packages and container
images.

### Security Groups

The control-plane security group permits:

- TCP 22 from the configurable administrator CIDR.
- A temporary TCP 22 `/32` rule for the current GitHub-hosted runner.
- All intra-VPC traffic, as required by the assignment.
- Outbound traffic for packages, AWS APIs, and images.

The worker security group permits:

- All intra-VPC traffic.
- Outbound traffic for packages, AWS APIs, and images.
- No permanent public SSH ingress.

The Kubernetes API is used from inside the VPC and through SSH-based bootstrap,
so TCP 6443 is not permanently exposed to the Internet.

## Control Plane

The control plane is:

- `t3.medium`.
- Canonical Ubuntu 24.04.
- An encrypted 20 GiB root volume.
- Associated with a dedicated IAM instance profile.

The role receives the assignment-required policies:

- `AmazonEKSClusterPolicy`
- `AmazonEBSCSIDriverPolicy`
- `AmazonEC2ContainerRegistryReadOnly`

A narrow custom policy allows it to update only the cluster's SSM join
parameter.

### Control-Plane User Data

The idempotent boot script:

1. Disables swap.
2. Loads required kernel modules.
3. Applies Kubernetes networking sysctls.
4. Installs CRI-O from the pinned `v1.35` repository.
5. Installs `kubelet`, `kubeadm`, and `kubectl` from the pinned `v1.35`
   repository and holds the packages.
6. Starts CRI-O and kubelet.
7. Runs `kubeadm init` only when `/etc/kubernetes/admin.conf` does not exist.
8. Configures `/home/ubuntu/.kube/config`.
9. Creates a non-expiring join command.
10. Stores the join command in the encrypted SSM parameter.

`kubeadm init` advertises the control-plane private address and uses
`192.168.0.0/16` as the pod-network CIDR.

## Worker Nodes

The worker launch template uses:

- The same Ubuntu, Kubernetes, and CRI-O release streams as the control plane.
- A configurable instance type, initially `t3.medium`.
- A worker IAM instance profile.
- Both public subnets through the ASG.

The worker role receives:

- `AmazonEC2ContainerRegistryReadOnly`.
- Permission to read and decrypt only the cluster join parameter.
- Narrow S3 and Bedrock permissions required by PolyAI workloads.

For this course-level self-managed cluster, pods use credentials available from
the worker instance role. The implementation documentation must identify
node-shared credentials as a limitation and recommend pod-level identity for a
production design.

### Worker Join

Terraform creates an encrypted SSM parameter with a placeholder. The control
plane replaces it after initialization.

Terraform ignores later changes to the parameter value so a subsequent plan
does not replace the real join command with the placeholder. Terraform
continues to manage the parameter's existence, name, encryption type, tags, and
lifecycle.

Worker user data:

1. Configures the operating system and installs CRI-O and Kubernetes.
2. Polls SSM for the join parameter with a bounded timeout.
3. Waits while the placeholder remains.
4. Runs the retrieved command when it begins with `kubeadm join`.
5. Skips joining if `/etc/kubernetes/kubelet.conf` already exists.

The join command is not exposed as a Terraform output, committed to Git, or
deliberately printed in cloud-init logs.

### Auto Scaling

AWS requires desired capacity to be at least the ASG minimum. To reconcile that
constraint with the assignment's idle-zero requirement:

```text
desired = 0   → min = 0, max = 3
desired = 1–3 → min = 1, max = 3
```

On scale-down, stale Kubernetes Node objects are handled manually:

```bash
kubectl drain <worker> --ignore-daemonsets --delete-emptydir-data
kubectl delete node <worker>
```

Lifecycle-hook/Lambda cleanup is intentionally omitted because the assignment
allows manual cleanup when lifecycle automation is not fully implemented and
explained.

## Terraform Outputs

Non-secret outputs include:

- Control-plane public and private IPs.
- Control-plane instance ID.
- Control-plane security-group ID.
- Worker ASG name.
- VPC ID.
- Public-subnet IDs.
- An SSH command example.

The join token, join command, private SSH key, and AWS credentials are never
outputs.

## Cluster Bootstrap

Part II is first performed manually to validate each operation:

1. Wait for control-plane cloud-init.
2. Confirm that the worker registered.
3. Install a pinned Calico release.
4. Wait for Nodes and Calico pods to become ready.
5. Install a pinned Argo CD release into `argocd`.
6. Wait for Argo CD components.
7. Apply the root Argo CD Application.
8. Verify child Applications and their sync policies.

After successful manual validation, these same operations become the idempotent
Bootstrap job in `cluster.yaml`.

## Argo CD Design

The four currently containerized microservices are:

- `agent`
- `frontend`
- `img-proc-mcp`
- `yolo`

Each service has a dev and prod Application:

```text
<service>-dev  → dev branch  → dev namespace  → automatic prune/self-heal
<service>-prod → main branch → prod namespace → manual synchronization
```

The manifest layout is:

```text
infra/k8s/
├── argo/
│   ├── app-of-apps.yaml
│   ├── agent-dev.yaml
│   ├── agent-prod.yaml
│   ├── frontend-dev.yaml
│   ├── frontend-prod.yaml
│   ├── img-proc-mcp-dev.yaml
│   ├── img-proc-mcp-prod.yaml
│   ├── yolo-dev.yaml
│   └── yolo-prod.yaml
├── dev/
│   ├── agent/
│   ├── frontend/
│   ├── img-proc-mcp/
│   └── yolo/
└── prod/
    ├── agent/
    ├── frontend/
    ├── img-proc-mcp/
    └── yolo/
```

The existing YOLO GitOps behavior is retained, including immutable image tags,
restricted pod settings, probes, resource controls, and its memory-safe
`Recreate` deployment strategy.

## GitHub Authentication and Secrets

The permanent bootstrap layer contains:

- The AWS GitHub OIDC provider.
- A dedicated IAM role whose trust policy restricts assumption to the intended
  repository and approved branch or environment contexts.

Repository configuration:

| Name | Type | Purpose |
|---|---|---|
| `AWS_TERRAFORM_ROLE_ARN` | Variable | OIDC role assumed by workflows |
| `CLUSTER_SSH_PRIVATE_KEY` | Secret | Bootstrap SSH access |
| `DOCKERHUB_USERNAME` | Secret | Image registry login |
| `DOCKERHUB_TOKEN` | Secret | Image registry login |

The role ARN is an identifier, not a secret. No long-lived AWS access key is
stored in GitHub.

## `cluster.yaml`

The workflow uses `workflow_dispatch` with a required `region` input and
contains two sequential jobs.

### Provision

1. Checkout the repository.
2. Request a GitHub OIDC token.
3. Assume the AWS provisioning role.
4. Initialize Terraform.
5. Select or create the regional workspace.
6. Validate and apply with `tfvars/<region>.tfvars`.
7. Export the control-plane IP and security-group ID for Bootstrap.

### Bootstrap

1. Assume the AWS role.
2. Detect the GitHub runner's public IPv4 address.
3. Add a temporary SSH `/32` security-group rule.
4. SSH to the control plane.
5. Wait for cloud-init with bounded retries.
6. Idempotently install and verify Calico.
7. Idempotently install and verify Argo CD.
8. Idempotently apply and verify Argo CD Applications.
9. Remove the temporary SSH rule with an always-run cleanup step.

Concurrency is scoped by region to prevent simultaneous operations against the
same Terraform state.

## `cd.yaml`

The CD workflow runs on pushes to `dev` and `main` affecting service source or
the workflow itself.

It:

1. Determines which containerized services changed.
2. Builds and pushes only those services.
3. Uses the triggering Git SHA as the immutable image tag.
4. Maps `dev` to `infra/k8s/dev/<service>` and `main` to
   `infra/k8s/prod/<service>`.
5. Updates and commits the matching manifests.
6. Pushes the `[skip ci]` commit to the triggering branch.

Branch-scoped concurrency prevents conflicting manifest commits. The workflow
must pull/rebase before pushing if another run updated the branch.

Existing direct-to-EC2 service workflows are retired or disabled to avoid
deploying the same service through both Docker Compose and Argo CD.

If branch rules later prevent the workflow token from pushing manifest updates,
the repository must use an approved GitHub App/bot path or an image-update PR;
the workflow must not be granted a broad human-role bypass.

## Validation

### Static validation

```bash
terraform fmt -check
terraform validate
terraform plan -var-file="tfvars/us-east-1.tfvars"
kubectl apply --dry-run=server
kubectl diff
```

Manifest review includes label/selector/port consistency, probes, resource
requests and limits, restricted security contexts, and immutable image tags.

### Runtime validation

```bash
cloud-init status --long
kubectl get nodes -o wide
kubectl get pods -A
kubectl get applications -n argocd
```

The implementation must verify:

- Automatic control-plane initialization.
- Automatic worker joining.
- Node readiness after Calico.
- Argo CD component health.
- Automatic dev reconciliation.
- Manual prod reconciliation.

### Resilience and completion tests

1. Terminate a worker and confirm its ASG replacement joins.
2. Scale workers to zero and manually remove the stale Node.
3. Scale workers back up and confirm new joining.
4. Push a dev service change and observe automatic deployment.
5. Merge a service change to main and observe manual prod promotion.
6. Destroy the new cluster.
7. Recreate and bootstrap it through `cluster.yaml`.

The old manual cluster is retired only after the complete path succeeds.

## Failure Handling

- Boot scripts stop on unexpected errors.
- Worker SSM polling has a timeout.
- Cloud-init, CRI-O, and kubelet logs remain available for diagnosis.
- Bootstrap waits for SSH and cloud-init with bounded retries.
- Temporary SSH access is removed even when Bootstrap fails.
- Bootstrap is idempotent and safe to rerun.
- State locking prevents concurrent Terraform writers.
- Failed image builds do not modify deployment manifests.
- Stale saved plans are regenerated rather than forced.

## Limitations

- The control plane is a single EC2 instance and is not highly available.
- Replacing the control plane recreates the cluster.
- Public subnets and public node addresses are appropriate for the assignment,
  not a hardened production topology.
- The non-expiring join token is a course-level reliability choice protected by
  SSM and IAM; production should rotate short-lived credentials.
- Worker credentials are shared at node level; production should use pod-level
  identity.
- Stale Node cleanup remains manual.

## Acceptance Criteria

The design is successfully implemented when:

- One Terraform configuration provisions the cluster in `us-east-1` and can be
  parameterized for another region without creating another cluster.
- The VPC contains two public subnets in different Availability Zones.
- The control plane initializes without manual kubeadm commands.
- ASG workers automatically join through SSM.
- Calico and Argo CD install idempotently.
- Every containerized microservice has dev and prod Argo CD Applications.
- Dev sync is automatic and prod sync is manual.
- Changed services receive immutable images and Git manifest updates.
- The complete cluster can be destroyed and recreated by the manual workflow.
- The existing cluster remains available until explicit retirement approval.
