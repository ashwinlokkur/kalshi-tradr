# Local Kubernetes deployment

These manifests deploy the bot + Postgres into any local Kubernetes cluster
(kind, k3d, minikube, Docker Desktop). Plain YAML + Kustomize — no Helm.

## Layout

| File | Purpose |
|---|---|
| `namespace.yaml` | `kalshi-tradr` namespace |
| `configmap.yaml` | Non-sensitive settings (env, scan thresholds, Kelly fraction, …) |
| `postgres.yaml` | Postgres 16 Deployment + PVC + ClusterIP Service |
| `bot.yaml` | Bot Deployment; mounts the Kalshi PEM from the Secret |
| `kustomization.yaml` | Ties everything under the `kalshi-tradr` namespace |

The Secret (`kalshi-tradr-secrets`) is **not** in-tree — you create it once
below.

## Steps

### 1. Build the image

```bash
docker build -t kalshi-tradr:local .
```

### 2. Load the image into your local cluster

The bot Deployment uses `imagePullPolicy: IfNotPresent` against the tag
`kalshi-tradr:local`, so the cluster must already have the image.

| Cluster | Command |
|---|---|
| kind | `kind load docker-image kalshi-tradr:local` |
| k3d  | `k3d image import kalshi-tradr:local -c <cluster>` |
| minikube | `minikube image load kalshi-tradr:local` |
| Docker Desktop Kubernetes | *(no-op — shares the host docker image cache)* |

### 3. Create the Secret

One Secret holds every sensitive value — Telegram token, Kalshi key ID,
Postgres credentials, the DSN, and the PEM file itself.

```bash
kubectl create namespace kalshi-tradr --dry-run=client -o yaml | kubectl apply -f -

kubectl -n kalshi-tradr create secret generic kalshi-tradr-secrets \
  --from-literal=TELEGRAM_BOT_TOKEN='123:xxxxxxxxxxxxxxxx' \
  --from-literal=TELEGRAM_ALLOWED_CHAT_IDS='11111111,22222222' \
  --from-literal=KALSHI_API_KEY_ID='your-kalshi-key-id' \
  --from-literal=POSTGRES_USER='kalshi' \
  --from-literal=POSTGRES_PASSWORD='kalshi' \
  --from-literal=POSTGRES_DB='kalshi_tradr' \
  --from-literal=DATABASE_URL='postgresql://kalshi:kalshi@postgres:5432/kalshi_tradr' \
  --from-file=kalshi.pem=./secrets/kalshi.pem
```

### 4. Apply manifests

```bash
kubectl apply -k k8s/
```

### 5. Verify

```bash
kubectl -n kalshi-tradr get pods
kubectl -n kalshi-tradr logs -f deploy/bot
```

Postgres isn't exposed outside the cluster; to `psql` into it:

```bash
kubectl -n kalshi-tradr exec -it deploy/postgres -- \
  psql postgresql://kalshi:kalshi@127.0.0.1:5432/kalshi_tradr
```

## Updating

Rebuild and redeploy after code changes:

```bash
docker build -t kalshi-tradr:local .
kind load docker-image kalshi-tradr:local        # or the equivalent for your cluster
kubectl -n kalshi-tradr rollout restart deploy/bot
```

## Teardown

```bash
kubectl delete -k k8s/
# Postgres PVC is deleted with the namespace; add --preserve-data by removing the PVC from postgres.yaml if you want it to survive.
```

## Notes

- **Single replica.** Telegram long-polling allows only one consumer per bot
  token; `bot` is pinned to `replicas: 1` with `strategy: Recreate`.
- **Flip to prod.** Edit `configmap.yaml` (`KALSHI_ENV: prod`) **only** after
  smoke-testing against `demo`. Apply the change with
  `kubectl apply -k k8s/ && kubectl -n kalshi-tradr rollout restart deploy/bot`.
- **Hard caps live in the ConfigMap.** `MAX_BET_USD`, `KELLY_FRACTION`, and
  `BET_CONFIRM_REQUIRED` are edited there and picked up on the next rollout.
