# PolyAI GitOps with Argo CD

Argo CD manages four PolyAI microservices across two environments:

| Service | Development Application | Production Application |
|---|---|---|
| Agent | `agent-dev` | `agent-prod` |
| Frontend | `frontend-dev` | `frontend-prod` |
| Image processing MCP | `img-proc-mcp-dev` | `img-proc-mcp-prod` |
| YOLO | `yolo-dev` | `yolo-prod` |

## GitOps flow

1. Application code is changed and tested.
2. CI builds a container image tagged with the Git commit SHA.
3. CI updates the corresponding Kubernetes manifest in Git.
4. Argo CD detects the manifest change.
5. Development synchronizes automatically.
6. Production waits for manual review and synchronization.

Git is the desired-state source of truth. GitHub Actions builds images and
updates Git; Argo CD is responsible for changing Kubernetes resources.

## Environment behavior

Development Applications:

- Follow the `dev` branch.
- Deploy into the `dev` namespace.
- Enable automatic synchronization.
- Enable pruning and self-healing.

Production Applications:

- Follow the `main` branch.
- Deploy into the `prod` namespace.
- Require manual synchronization.
- Do not automatically prune resources.

The namespaces and their Pod Security Admission labels are managed centrally by
`infra/k8s/00-namespaces.yaml`, not by individual Applications.

## App-of-apps

`app-of-apps.yaml` is the root Argo CD Application. It follows `main` and reads
the Application definitions from `infra/k8s/argo`.

It creates eight child Applications while excluding itself to prevent recursive
self-management.

## Bootstrap

Create the namespaces:

```bash
kubectl apply -f infra/k8s/00-namespaces.yaml
```

Install Argo CD v3.4.2:

```bash
kubectl create namespace argocd

kubectl apply \
  --server-side \
  --force-conflicts \
  -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.4.2/manifests/install.yaml
```

These commands must run on the control-plane EC2 instance, where `kubectl` has
the cluster kubeconfig. Argo CD is already installed on the current cluster.

After the manifests are committed and pushed, bootstrap the root Application:

```bash
kubectl apply \
  -n argocd \
  -f infra/k8s/argo/app-of-apps.yaml
```

## Observe applications

```bash
kubectl get applications -n argocd
kubectl get deployments,pods,services -n dev
kubectl get deployments,pods,services -n prod
```

## Production promotion

Production does not synchronize automatically. Review and synchronize the
selected production Application in the Argo CD UI:

1. Open `<service>-prod`.
2. Select **Diff**.
3. Review the proposed changes.
4. Select **Sync**.

## Rollback

Revert the Git commit that changed the deployment manifest:

```bash
git revert <deployment-commit>
git push
```

Development reconciles the revert automatically. Production requires another
review and manual synchronization.

Avoid `kubectl rollout undo` as the normal rollback method because Argo CD sees
it as drift from Git.