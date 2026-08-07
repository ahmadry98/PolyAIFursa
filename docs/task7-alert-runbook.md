# Task 7 Alert Verification Runbook

This runbook demonstrates the complete Prometheus → Alertmanager → SNS → email path using the development agent. Run it only while actively watching the cluster, and restore the deployment immediately after collecting evidence.

## Preconditions

- Confirm the SNS subscription from the inbox configured by the cluster workflow.
- Confirm `agent` is `UP` in Prometheus under **Status → Target health**.
- Confirm `AgentHighErrorRate` is visible and inactive under **Alerts**.
- Keep a terminal open with `kubectl get prometheusrule -A` and another with the Prometheus Alerts page.

## Generate a controlled failure

Temporarily stop Argo CD self-healing for the dev agent, save the current model, and switch the agent to an invalid model identifier:

```bash
kubectl patch application agent-dev -n argocd --type merge \
  -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":false}}}}'

current_model="$(kubectl get deployment agent -n dev \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="MODEL")].value}')"

kubectl set env deployment/agent -n dev MODEL=bedrock/invalid-alert-test-model
kubectl rollout status deployment/agent -n dev --timeout=180s
```

Send repeated valid chat requests. The invalid model makes the request reach the agent handler and increment `agent_chat_requests_total{status="error"}`:

```bash
for request in $(seq 1 30); do
  curl -sS -o /dev/null \
    -H 'content-type: application/json' \
    -d '{"messages":[{"role":"user","content":"alert verification"}]}' \
    https://api-dev.fursa.click/chat || true
  sleep 2
done
```

Capture evidence in this order:

1. `AgentHighErrorRate` is `Pending` in Prometheus.
2. It becomes `Firing` after the configured two-minute `for` duration.
3. Alertmanager shows the active alert routed to `sns-email`.
4. The subscribed mailbox receives the firing notification.

## Restore service

Restore the original model and Argo CD self-healing:

```bash
kubectl set env deployment/agent -n dev "MODEL=${current_model}"
kubectl rollout status deployment/agent -n dev --timeout=180s

kubectl patch application agent-dev -n argocd --type merge \
  -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
```

Send successful requests until the five-minute error-rate window clears. Confirm that:

1. The Prometheus alert returns to inactive.
2. Alertmanager removes the active alert.
3. The mailbox receives a `RESOLVED` notification.

## Recovery

If the rollout does not recover, re-enable Argo CD self-healing first and force a refresh:

```bash
kubectl annotate application agent-dev -n argocd \
  argocd.argoproj.io/refresh=hard --overwrite
kubectl rollout status deployment/agent -n dev --timeout=300s
```

Never leave the invalid model configured after the demonstration.
