# Cluster Autoscaler Bonus Runbook

Run the cluster workflow with `enable_cluster_autoscaler` selected and at least one worker online.

Apply the test workload and watch the scheduling and ASG events:

```bash
kubectl apply -f infra/k8s/autoscaler/scale-test.yaml
kubectl get pods -n dev -l app.kubernetes.io/name=cluster-autoscaler-scale-test -w
kubectl logs deployment/cluster-autoscaler -n kube-system -f
aws autoscaling describe-auto-scaling-groups \
  --auto-scaling-group-names "$(terraform -chdir=infra/tf output -raw worker_asg_name)"
```

Capture evidence that a test pod was initially `Pending`, the ASG launched another worker, the new node became `Ready`, and the pod was scheduled.

Remove the test workload and watch the autoscaler scale the unused node down after its configured grace period:

```bash
kubectl delete -f infra/k8s/autoscaler/scale-test.yaml
kubectl get nodes -w
```

When the demonstration is finished, set `worker_desired_capacity = 0` in the regional tfvars, apply Terraform, and confirm the ASG desired capacity is zero to avoid unnecessary cost.
