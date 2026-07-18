# Task 5 Report: Kubernetes Migration, Observability, and MCP Tooling

## Summary

Task 5 is implemented and verified.

The Docker Compose application was migrated to Kubernetes using plain manifests in `infra/k8s/`. The cluster has separate `dev` and `prod` namespaces. The frontend and backend services use internal ClusterIP services and are reached for testing through `kubectl port-forward`. The browser calls the agent directly through a local agent port-forward, while YOLO and the image-processing service remain internal. Prometheus and Grafana run in Kubernetes with EBS-backed persistent storage. Agent metrics are exposed through `/metrics`, scraped by Prometheus, and visualized in Grafana. The old Docker Compose EC2 deployment keeps running and sends logs to S3 using Fluent Bit. A local Observability MCP server can query Prometheus and read S3 logs.

## Kubernetes Deployment

Implemented manifests:

- `infra/k8s/00-namespaces.yaml`
- `infra/k8s/agent.yaml`
- `infra/k8s/frontend.yaml`
- `infra/k8s/frontend-prod.yaml`
- `infra/k8s/yolo.yaml`
- `infra/k8s/img-proc-mcp.yaml`
- `infra/k8s/prometheus.yaml`
- `infra/k8s/grafana.yaml`
- `infra/k8s/hpa.yaml`

Namespaces:

- `dev`
- `prod`

Frontend access:

- Dev:
  - run `kubectl port-forward -n dev svc/frontend-svc 3000:3000`
  - run `kubectl port-forward -n dev svc/agent-svc 8000:8000`
  - open `http://localhost:3000`
- Prod:
  - run `kubectl port-forward -n prod svc/frontend-svc 3001:3000`
  - run `kubectl port-forward -n prod svc/agent-svc 8000:8000`
  - open `http://localhost:3001`

Ports `3000`, `3001`, and `8000` are local ports on the machine running `kubectl port-forward`. The Kubernetes services still expose only their normal service ports inside the cluster. If dev and prod must be tested at the same time, use separate local agent ports and build or configure the frontend with the matching `NEXT_PUBLIC_AGENT_URL`.

Internal services:

- `agent-svc`
- `yolo-svc`
- `img-proc-mcp-svc`
- `prometheus-svc`
- `grafana-svc`

`node-exporter` was not migrated to Kubernetes, as required.

## Safe Apply Commands

Do not apply the whole `infra/k8s/` folder to `prod`, because it contains both the dev frontend file and the prod frontend file.

Do not run:

```bash
kubectl apply -n prod -f infra/k8s/
```

Use this instead:

```bash
kubectl apply -f infra/k8s/00-namespaces.yaml

kubectl apply -n dev -f infra/k8s/agent.yaml
kubectl apply -n dev -f infra/k8s/frontend.yaml
kubectl apply -n dev -f infra/k8s/yolo.yaml
kubectl apply -n dev -f infra/k8s/img-proc-mcp.yaml
kubectl apply -n dev -f infra/k8s/prometheus.yaml
kubectl apply -n dev -f infra/k8s/grafana.yaml
kubectl apply -n dev -f infra/k8s/hpa.yaml

kubectl apply -n prod -f infra/k8s/agent.yaml
kubectl apply -n prod -f infra/k8s/frontend-prod.yaml
kubectl apply -n prod -f infra/k8s/yolo.yaml
kubectl apply -n prod -f infra/k8s/img-proc-mcp.yaml
kubectl apply -n prod -f infra/k8s/prometheus.yaml
kubectl apply -n prod -f infra/k8s/grafana.yaml
kubectl apply -n prod -f infra/k8s/hpa.yaml
```

## Verification Commands

Cluster health:

```bash
kubectl get pods,svc,pvc,hpa -n dev
kubectl get pods,svc,pvc,hpa -n prod
kubectl top nodes
kubectl top pods -n dev
kubectl top pods -n prod
```

Expected state:

- All application pods are `1/1 Running`.
- Dev frontend service is `ClusterIP`.
- Prod frontend service is `ClusterIP`.
- Backend services are `ClusterIP`.
- Grafana and Prometheus PVCs are `Bound`.
- HPA targets show real CPU values, not `<unknown>`.

Latest verified state:

- Dev pods: agent, frontend, grafana, img-proc-mcp, prometheus, yolo all running.
- Prod pods: agent, frontend, grafana, img-proc-mcp, prometheus, yolo all running.
- Node usage was healthy:
  - control plane: about `7%` CPU, `38%` memory
  - worker: about `4%` CPU, `63%` memory

## HPA

HPA is configured for:

- `agent`
- `frontend`
- `yolo`

Configuration:

- minimum replicas: `1`
- maximum replicas: `3`
- target CPU utilization: `50%`

Verified HPA values:

- Dev:
  - agent around `2%/50%`
  - frontend around `1%/50%`
  - yolo around `3%/50%`
- Prod:
  - agent around `2%/50%`
  - frontend around `1%/50%`
  - yolo around `3%/50%`

Metrics Server was installed and fixed so `kubectl top` and HPA CPU targets work.

## Prometheus and Grafana

Prometheus and Grafana are deployed in Kubernetes using plain manifests.

Persistent storage:

- `prometheus-pvc`: `5Gi`, EBS storage class
- `grafana-pvc`: `2Gi`, EBS storage class

Prometheus scrape targets were verified:

```bash
curl 'http://localhost:9090/api/v1/query?query=up'
```

Verified targets:

- `agent-svc:8000`
- `yolo-svc:8080`
- `prometheus`

Grafana dashboard:

- `infra/grafana/dashboards/agent.json`

The dashboard was imported into Grafana and showed agent latency data.

## Agent Metrics

Agent metrics were added with `prometheus_client`.

Metrics endpoint:

```text
/metrics
```

Verified metrics:

- `agent_chat_requests_total`
- `agent_chat_request_latency_seconds`
- `agent_chat_tokens_total`

Verification command:

```bash
kubectl exec -n dev deploy/agent -- python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/metrics').read().decode())" | grep agent_chat
```

Verified result included:

```text
agent_chat_requests_total{status="success"} 5.0
agent_chat_tokens_total{type="total"} 7621.0
```

## Fluent Bit to S3

Fluent Bit was added to the old Docker Compose EC2 deployment, not the Kubernetes cluster.

Files:

- `compose.yaml`
- `fluent-bit.conf`

S3 bucket:

```text
ahmad-polyai-logs
```

Lifecycle rule:

- Logs expire after 90 days.

Verification command:

```bash
aws s3 ls s3://ahmad-polyai-logs/logs/2026/07/15/ --recursive
```

Verified result:

```text
logs/2026/07/15/var_074630.gz-object...
logs/2026/07/15/var_074725.gz-object...
logs/2026/07/15/var_074730.gz-object...
```

## Observability MCP

The local MCP server is implemented under:

```text
services/observability-mcp/
```

Files:

- `services/observability-mcp/app.py`
- `services/observability-mcp/requirements.txt`
- `.vscode/mcp.json`

Tools:

- `list_log_objects(environment, prefix="logs/", limit=20)`
- `get_recent_logs(environment, minutes=5, limit=50)`
- `query_prometheus(environment, query)`
- `get_cpu_usage(environment, minutes=10)`

Environment variables:

```bash
export PROD_PROMETHEUS_URL=http://localhost:9090
export PROD_S3_LOGS_BUCKET=ahmad-polyai-logs
export DEV_PROMETHEUS_URL=http://localhost:9091
export DEV_S3_LOGS_BUCKET=ahmad-polyai-logs
export AWS_REGION=us-east-1
```

Prod Prometheus port-forward:

```bash
kubectl port-forward -n prod svc/prometheus-svc 9090:9090
```

Dev Prometheus port-forward:

```bash
kubectl port-forward -n dev svc/prometheus-svc 9091:9090
```

Verification command:

```bash
python - <<'PY'
import sys
sys.path.insert(0, "services/observability-mcp")
import app

print(app.query_prometheus("prod", "agent_chat_requests_total"))
print(app.list_log_objects("prod", limit=3))
print(app.get_recent_logs("prod", minutes=180, limit=3))
PY
```

Verified result:

- Prometheus returned `status: success`.
- S3 object listing returned log objects from `ahmad-polyai-logs`.
- Recent logs returned parsed log records from S3.

## Known Limitations

- CI/CD is not implemented because it was not required by the task.
- Ingress is not implemented because `kubectl port-forward` is enough for the current testing workflow.
- Kubernetes Fluent Bit is not implemented because the task required Fluent Bit for the old Docker Compose EC2 deployment.
- The current raw-manifest layout requires applying prod file-by-file because dev and prod frontend settings live in separate frontend files.
- The browser-direct frontend flow requires an agent port-forward, because `agent-svc` is intentionally still a private `ClusterIP` service.

## Final Status

Implementation is complete.

Remaining manual action:

- Commit and push the final report.
