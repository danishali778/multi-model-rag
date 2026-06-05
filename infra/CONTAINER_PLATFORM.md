# Container Platform Guide

This repository now supports a production-shaped container platform with:

- separate API and worker image targets from one Dockerfile
- separate API and worker runtime roles
- a default Docker stack that keeps Supabase remote
- an optional local-Supabase mode for fully local DB/Auth/Storage
- Kubernetes app-tier manifests for `dev`, `staging`, and `prod`

## Local startup

### Default: remote Supabase

1. Install Docker Desktop and Python.
2. Copy `.env.compose.example` to `.env.compose`.
3. Fill in remote Supabase credentials and provider keys.
4. Start the Docker stack:

```bash
./scripts/bootstrap_compose_remote.sh
```

PowerShell:

```powershell
.\scripts\bootstrap_compose_remote.ps1
```

The default bootstrap flow:

1. validates `.env.compose`
2. validates the Compose configuration
3. starts the app-side services
4. waits for API readiness
5. verifies database bootstrap and the `evaluation_runs` table against remote Supabase

### Optional: local Supabase

Use this mode only when you explicitly want local DB/Auth/Storage.

```bash
python scripts/generate_local_supabase_env.py compose .env.compose.local-supabase
./scripts/bootstrap_local_supabase_stack.sh
```

PowerShell:

```powershell
python scripts/generate_local_supabase_env.py compose .env.compose.local-supabase
.\scripts\bootstrap_local_supabase_stack.ps1
```

## Worker runtime

- API command: `/app/infra/docker/api-start.sh`
- Worker command: `/app/infra/docker/worker-start.sh`
- Worker health probe: `python scripts/healthcheck_worker.py`

The API and worker share one codebase but build different targets:

- `api-runtime`
  - installs core runtime dependencies only
- `worker-runtime`
  - installs core runtime dependencies plus ingestion extras such as `docling`

This split keeps ordinary API rebuilds lighter while preserving heavy parser support in the worker.

Both containers still use the same environment contract and differ mainly by:

- `RUNTIME_ROLE=worker`
- `TELEMETRY_SERVICE_NAME=multi-model-rag-worker`

## Health verification

Use:

- `GET /health`
- `GET /ready`
- `GET /metrics`

Key local endpoints:

- API: `http://localhost:8000`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001`

## Queue and backlog checks

- Worker availability is exposed through the worker metrics scrape target.
- Redis health is exposed through `redis_exporter`.
- Ingestion transition counters are available in Grafana and Prometheus through `rag_ingestion_jobs_total`.

## Migration execution

- App startup runs database bootstrap and migrations automatically when `SUPABASE_DB_URL` is configured.
- Both bootstrap paths run `scripts/verify_runtime_bootstrap.py` to confirm migration state.
- Production rollouts should run a one-shot migration check before scaling API or worker replicas.

## Rollout and rollback expectations

- Build and tag both the API and worker targets from the same Dockerfile revision.
- Roll out API and worker independently.
- Apply Kubernetes overlays with environment-specific images, secrets, and ingress hosts.
- Roll back by redeploying the prior image tag and keeping DB/Auth/Storage external and unchanged.
