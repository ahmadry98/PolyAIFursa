# YOLO GitOps with Argo CD

## What happens

1. A push that changes `services/yolo` on `dev` or `main` starts the GitHub Actions workflow.
2. The workflow builds and pushes `polyai-fursa-yolo:<git-sha>` to Docker Hub.
3. The workflow changes the image in the matching Git manifest and commits it back.
4. Argo CD notices that Git changed. `yolo-dev` syncs automatically; `yolo-prod` waits for a manual sync.

The cluster is changed by Argo CD, not by GitHub Actions. Git remains the desired-state audit trail.

## Assumptions

- Kubernetes 1.25 or newer with a CNI that enforces NetworkPolicy if policies are later added.
- Argo CD is installed in the `argocd` namespace.
- This public repository is reachable by Argo CD. A private repository needs repository credentials in Argo CD.
- GitHub contains `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets.
- The SHA currently in each deployment must exist in Docker Hub. The next successful workflow run replaces it.
- `dev` and `main` branches both contain their corresponding manifest directories and the workflow.

## One-time bootstrap

Install Argo CD only after checking the manifest version you intend to run. Pinning a release is safer than relying permanently on the moving `stable` URL:

```bash
kubectl create namespace argocd
kubectl apply --server-side -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl rollout status deployment/argocd-server -n argocd --timeout=5m
```

Commit and push these files before bootstrapping the root application:

```bash
kubectl apply --dry-run=server -f infra/k8s/argo/app-of-apps.yaml
kubectl apply -f infra/k8s/argo/app-of-apps.yaml
kubectl get applications -n argocd
```

The root app reads `main` and creates the two child applications. Its directory rule excludes itself, avoiding recursive self-management.

## Observe dev

```bash
kubectl get application yolo-dev -n argocd
kubectl get deployment,pods,service -n dev
kubectl rollout status deployment/yolo -n dev
```

To inspect the UI locally:

```bash
kubectl port-forward service/argocd-server -n argocd 8080:443
```

Open `https://localhost:8080`. The username is `admin`; retrieve the temporary password with:

```bash
kubectl get secret argocd-initial-admin-secret -n argocd \
  -o jsonpath='{.data.password}' | base64 --decode
```

Change the password and remove the initial secret after first login.

## Promote prod

The `main` workflow updates `infra/k8s/prod/yolo/deployment.yaml`, but prod does not auto-sync. Review first:

```bash
argocd app diff yolo-prod
argocd app sync yolo-prod
argocd app wait yolo-prod --health
```

In the UI, the equivalent is **yolo-prod → Diff → Sync**.

## Roll back

GitOps rollback means reverting the manifest commit so Git and the cluster agree:

```bash
git revert <deployment-commit>
git push
```

Dev reconciles the revert automatically. For prod, review the Argo CD diff and sync again. `kubectl rollout undo` is only an emergency measure: Argo CD will see it as drift, so follow it with a Git revert.

## Important boundaries

- Dev owns only resources under `infra/k8s/dev/yolo`; automated pruning is safe only while that ownership stays narrow.
- Prod deliberately has no `automated` policy.
- Do not store AWS keys or other plaintext secrets in this repository. Use workload identity or a secrets operator for credentials.
- Installing Argo CD grants a controller significant cluster access. Restrict its projects/RBAC before using this design for a shared or production cluster.
