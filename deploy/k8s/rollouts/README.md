# Argo Rollouts

The Helm chart includes a Rollout template (gated by `backend.rollout.enabled`)
that switches the backend off `apps/v1 Deployment` and onto
`argoproj.io/v1alpha1 Rollout` with a canary or blue/green strategy.

## Install the controller (once per cluster)

```bash
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts \
  -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml
```

`kubectl-argo-rollouts` plug-in is useful for `promote / pause / abort`:

```bash
curl -L https://github.com/argoproj/argo-rollouts/releases/latest/download/kubectl-argo-rollouts-linux-amd64 \
  -o /usr/local/bin/kubectl-argo-rollouts
chmod +x /usr/local/bin/kubectl-argo-rollouts
```

## Switch the chart to canary

```bash
helm upgrade --install telegram-ai-agent deploy/helm/telegram-ai-agent \
  --namespace tgai-prod \
  -f deploy/helm/telegram-ai-agent/values.yaml \
  -f deploy/helm/telegram-ai-agent/values-production.yaml \
  --set image.tag=${VERSION} \
  --set backend.rollout.enabled=true \
  --set backend.rollout.strategy=canary
```

The default canary steps in `values-production.yaml`:
`10% → pause 2 min → 30% → 5 min → 60% → 5 min → 100%`.

Promote / abort manually:

```bash
kubectl argo rollouts -n tgai-prod status   release-backend
kubectl argo rollouts -n tgai-prod promote  release-backend
kubectl argo rollouts -n tgai-prod abort    release-backend
kubectl argo rollouts -n tgai-prod undo     release-backend  # rollback
```

## Blue/Green

For an explicit blue/green swap set the strategy and provision a preview
Service. A minimal preview Service is in
[`backend-preview-service.example.yaml`](./backend-preview-service.example.yaml).

```bash
kubectl apply -f deploy/k8s/rollouts/backend-preview-service.example.yaml
helm upgrade ... --set backend.rollout.enabled=true \
                  --set backend.rollout.strategy=blueGreen
```
