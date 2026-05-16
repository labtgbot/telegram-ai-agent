# Secrets management

Two paths are supported — pick one per cluster. The Helm chart never bundles
real credentials; it only references a Secret named after
`secret.name` in `values.yaml` (default: `telegram-ai-agent-backend`).

## Option A — sealed-secrets

Encrypt locally, commit the encrypted manifest, the controller decrypts
in-cluster.

```bash
# 1. Build a plain Secret stub (not committed).
kubectl create secret generic telegram-ai-agent-backend \
  --namespace tgai-prod \
  --from-literal=TELEGRAM_BOT_TOKEN=… \
  --from-literal=APP_SECRET=… \
  --from-literal=ADMIN_JWT_SECRET=… \
  --from-literal=DATABASE_URL=postgresql+asyncpg://… \
  --from-literal=REDIS_URL=redis://… \
  --from-literal=COMPOSIO_API_KEY=… \
  --from-literal=GEMINI_API_KEY=… \
  --from-literal=ANTHROPIC_API_KEY=… \
  --from-literal=OPENAI_API_KEY=… \
  --from-literal=PAYMENT_PROVIDER_TOKEN=… \
  --dry-run=client -o yaml > /tmp/plain-secret.yaml

# 2. Seal it (writes to deploy/k8s/secrets/sealed-secret.example.yaml format).
kubeseal --controller-namespace=sealed-secrets \
  --controller-name=sealed-secrets-controller \
  --format=yaml \
  < /tmp/plain-secret.yaml \
  > deploy/k8s/secrets/<env>/sealed-secret.yaml

# 3. Apply.
kubectl apply -f deploy/k8s/secrets/<env>/sealed-secret.yaml

# 4. Verify.
kubectl -n tgai-prod get secret telegram-ai-agent-backend
```

See [`sealed-secret.example.yaml`](./sealed-secret.example.yaml) for the
resulting shape — values are stubs, not real ciphertext.

## Option B — external-secrets

Cluster pulls secrets from AWS Secrets Manager / GCP Secret Manager / Vault.

```bash
# 1. Configure the SecretStore (cluster credentials → external provider).
kubectl apply -f deploy/k8s/secrets/secret-store.example.yaml

# 2. Configure the ExternalSecret (which provider keys map to which env vars).
kubectl apply -f deploy/k8s/secrets/external-secret.example.yaml

# 3. external-secrets reconciles and materialises
#    Secret/telegram-ai-agent-backend in the namespace.
```

## Local-only fallback

For local docker-compose or kind-based smoke tests you can render the
placeholder Secret from the chart itself:

```bash
helm template telegram-ai-agent deploy/helm/telegram-ai-agent \
  --set secret.create=true \
  --set secret.defaults.TELEGRAM_BOT_TOKEN=… \
  | kubectl apply -f -
```

Never commit values from this path — `secret.create` is off by default and the
chart sets `helm.sh/resource-policy: keep` so a `helm uninstall` will not wipe
a manually applied secret out from under a running stack.
