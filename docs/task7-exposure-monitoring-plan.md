# Task 7: Exposing the Cluster and Production-Grade Monitoring

## Working branch

`task-7-exposure-monitoring`, created from `main` at `bc048d6`.

## Assumptions

- Kubernetes is a self-managed kubeadm cluster on AWS EC2, currently pinned to Kubernetes 1.35.
- Worker nodes are managed by an Auto Scaling Group in two public subnets.
- Calico provides pod networking, Argo CD owns application manifests, and Helm owns platform add-ons.
- The shared `fursa.click` Route 53 hosted zone already exists and must only be read through a Terraform data source.
- The ALB terminates HTTPS and forwards HTTP to ingress-nginx on fixed NodePort `30080`.
- Chart versions and all operational settings are pinned in code so destroy/rebuild remains reproducible.

## Part 1: Public ingress infrastructure

1. Add variables for the public hostnames, fixed NodePorts, alert email address, and optional autoscaler settings.
2. Look up the existing `fursa.click` hosted zone using `data "aws_route53_zone"`.
3. Provision an ACM certificate and DNS validation records for the public hostnames.
4. Provision an internet-facing ALB across both public subnets.
5. Add an HTTPS listener on port 443 and an instance target group forwarding to worker NodePort `30080`.
6. Attach the existing worker ASG to the target group.
7. Restrict worker NodePort ingress to the ALB security group.
8. Create Route 53 alias records for dev/prod frontend and agent, Grafana, Prometheus, and Argo CD.
9. Export the ALB DNS name and public URLs.

Validation: run `terraform fmt -check`, `terraform validate`, review `terraform plan`, and confirm the shared hosted zone is never in the destroy plan.

## Part 2: ingress-nginx

1. Commit an ingress-nginx values file with a pinned chart version in the bootstrap workflow.
2. Configure its Service as `NodePort` with HTTP `30080` and HTTPS `30443`.
3. Enable controller Prometheus metrics and its ServiceMonitor.
4. Set resource requests/limits and deliberate traffic/health-check settings.
5. Wait for the controller rollout and verify the fixed NodePorts during bootstrap.

## Part 3: Application ingress resources

Add `networking.k8s.io/v1` Ingress resources with `ingressClassName: nginx` for:

- Dev frontend and agent.
- Prod frontend and agent.
- Grafana and Prometheus.
- Argo CD, including the correct backend protocol configuration.

Validate every host, namespace, backend Service name, named port, selector, and endpoint before deployment.

## Part 4: kube-prometheus-stack migration

1. Remove the legacy `infra/k8s/prometheus.yaml` and `infra/k8s/grafana.yaml` resources.
2. Commit `infra/k8s/monitoring/values.yaml` for a pinned `kube-prometheus-stack` chart.
3. Configure Prometheus with `ebs-sc`, 3 GiB storage, and 30-day retention.
4. Configure Grafana with `ebs-sc` and 1 GiB persistent storage.
5. Enable Alertmanager and resolved notifications without committing credentials.
6. Update bootstrap ordering so CRDs exist before ServiceMonitor and PrometheusRule resources.
7. Wait for the operator, Prometheus, Grafana, and Alertmanager rollouts.

## Part 5: Service monitoring and dashboards

1. Add ServiceMonitors for agent and YOLO in dev and prod, scraping the named HTTP Service ports at `/metrics`.
2. Allow Prometheus to discover monitors and rules across the required namespaces.
3. Enable ingress-nginx metric scraping.
4. Provision Grafana dashboard 9614 as code through the Grafana dashboard sidecar.
5. Verify all application and ingress targets are `UP` and that dashboard panels show request rate, latency, and status codes per host.

## Part 6: Alerting through SNS

1. Provision an SNS topic and email subscription in Terraform.
2. Grant only `sns:Publish` to that topic through the worker role used by Alertmanager on this self-managed cluster.
3. Configure Alertmanager's native `sns_configs` receiver with `send_resolved: true`.
4. Document the one-time email subscription confirmation step.
5. Add at least two actionable PrometheusRule alerts with different severities, based on real agent and YOLO metrics.

## Part 7: End-to-end proof

1. Generate normal traffic to establish a baseline.
2. Trigger a controlled error-rate or latency failure.
3. Capture evidence of `Pending`, then `Firing`, Alertmanager delivery, and the SNS email.
4. Remove the failure and capture the `RESOLVED` notification.
5. Store repeatable test commands and recovery steps in a runbook.

## Part 8: Destroy/rebuild acceptance test

1. Run `terraform destroy`.
2. Re-run the provision and bootstrap workflow.
3. Confirm worker registration, Argo CD sync, ingress readiness, PVC binding, public HTTPS endpoints, and Prometheus targets.
4. Repeat a small alert test.

## Bonus: Cluster Autoscaler

1. Add required ASG discovery tags and a least-privilege scaling policy in Terraform.
2. Install a Kubernetes-version-compatible Cluster Autoscaler chart through bootstrap.
3. Deploy an intentionally unschedulable workload and verify ASG scale-out, node registration, and scheduling.
4. Delete the workload and verify scale-in.
5. Return `worker_desired_capacity` to `0` after the demonstration to prevent unnecessary cost.

## Main risks and controls

- **Network exposure:** only the ALB can reach the ingress NodePort; application Services remain ClusterIP.
- **AWS privilege scope:** SNS and autoscaling policies are resource/action scoped; no static AWS credentials are committed.
- **Operator ordering:** monitoring CRDs are installed before custom resources.
- **GitOps ownership:** application resources stay in their existing Argo CD paths; platform add-ons have explicit bootstrap ownership.
- **Persistent storage:** Prometheus and Grafana use EBS-backed ReadWriteOnce claims and rollout validation.
- **Recovery:** use reviewed Terraform plans, Helm rollback, Argo CD diff/sync checks, and preserve the shared Route 53 zone.
