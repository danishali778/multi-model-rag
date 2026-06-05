#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

command -v docker >/dev/null 2>&1 || {
  echo "docker is required."
  exit 1
}
command -v python >/dev/null 2>&1 || {
  echo "python is required."
  exit 1
}

python scripts/run_supabase_cli.py start --ignore-health-check
python scripts/generate_local_supabase_env.py compose .env.compose.local-supabase
python scripts/validate_runtime_env.py .env.compose.local-supabase local-supabase-compose
mkdir -p .tmp
python scripts/generate_local_supabase_env.py host .tmp/.env.host.local-supabase-bootstrap
SERVICE_ROLE_KEY=$(python - <<'PY'
from pathlib import Path
for line in Path(".tmp/.env.host.local-supabase-bootstrap").read_text(encoding="utf-8").splitlines():
    if line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
        print(line.split("=", 1)[1])
        break
PY
)
SUPABASE_URL=$(python - <<'PY'
from pathlib import Path
for line in Path(".tmp/.env.host.local-supabase-bootstrap").read_text(encoding="utf-8").splitlines():
    if line.startswith("SUPABASE_URL="):
        print(line.split("=", 1)[1])
        break
PY
)
python scripts/bootstrap_supabase_storage.py "$SUPABASE_URL" "$SERVICE_ROLE_KEY" "raw-documents,processed-documents,voice-artifacts"
python scripts/run_docker_compose.py --env-file .env.compose.local-supabase up --build -d redis redis-exporter otel-collector prometheus grafana worker api
python scripts/wait_for_http.py http://localhost:8000/ready 120
python scripts/run_docker_compose.py --env-file .env.compose.local-supabase exec -T api python scripts/verify_runtime_bootstrap.py

cat <<'EOF'
Local stack is ready.
- API: http://localhost:8000
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001
EOF
