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

python scripts/validate_runtime_env.py .env.compose remote-compose
python scripts/run_docker_compose.py --env-file .env.compose config
python scripts/run_docker_compose.py --env-file .env.compose up --build -d redis redis-exporter otel-collector prometheus grafana worker api
python scripts/wait_for_http.py http://localhost:8000/ready 120
python scripts/run_docker_compose.py --env-file .env.compose exec -T api python scripts/verify_runtime_bootstrap.py

cat <<'EOF'
Remote-Supabase Docker stack is ready.
- API: http://localhost:8000
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001
EOF
