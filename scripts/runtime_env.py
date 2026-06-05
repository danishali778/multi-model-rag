from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse, urlunparse

REMOTE_COMPOSE_REQUIRED_KEYS = (
    "SUPABASE_DB_URL",
    "SUPABASE_JWKS_URL",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_RAW_DOCUMENTS_BUCKET",
    "SUPABASE_PROCESSED_DOCUMENTS_BUCKET",
    "SUPABASE_VOICE_BUCKET",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
)

LOCAL_SUPABASE_REQUIRED_KEYS = (
    "SUPABASE_DB_URL",
    "SUPABASE_JWKS_URL",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
)


def parse_env_lines(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
            normalized = normalized[1:-1]
        values[key.strip()] = normalized
    return values


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return parse_env_lines(path.read_text(encoding="utf-8"))


def replace_hostname(value: str, hostname: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        return value
    port = f":{parsed.port}" if parsed.port else ""
    netloc = hostname + port
    return urlunparse(parsed._replace(netloc=netloc))


def compose_local_supabase_overrides(supabase: dict[str, str]) -> dict[str, str]:
    api_url = replace_hostname(supabase["API_URL"], "host.docker.internal")
    db_url = replace_hostname(supabase["DB_URL"], "host.docker.internal")
    return {
        "SUPABASE_URL": api_url,
        "SUPABASE_DB_URL": db_url,
        "SUPABASE_JWKS_URL": f"{api_url}/auth/v1/.well-known/jwks.json",
        "SUPABASE_ANON_KEY": supabase.get("ANON_KEY", ""),
        "SUPABASE_SERVICE_ROLE_KEY": supabase.get("SERVICE_ROLE_KEY", ""),
        "REDIS_URL": "redis://redis:6379/0",
        "CELERY_BROKER_URL": "redis://redis:6379/0",
        "CELERY_RESULT_BACKEND": "redis://redis:6379/0",
        "CELERY_TASK_ALWAYS_EAGER": "false",
        "TRACING_ENABLED": "true",
        "TRACING_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4317",
    }


def host_local_supabase_overrides(supabase: dict[str, str]) -> dict[str, str]:
    api_url = replace_hostname(supabase["API_URL"], "127.0.0.1")
    db_url = replace_hostname(supabase["DB_URL"], "127.0.0.1")
    return {
        "SUPABASE_URL": api_url,
        "SUPABASE_DB_URL": db_url,
        "SUPABASE_JWKS_URL": f"{api_url}/auth/v1/.well-known/jwks.json",
        "SUPABASE_ANON_KEY": supabase.get("ANON_KEY", ""),
        "SUPABASE_SERVICE_ROLE_KEY": supabase.get("SERVICE_ROLE_KEY", ""),
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "CELERY_BROKER_URL": "redis://127.0.0.1:6379/0",
        "CELERY_RESULT_BACKEND": "redis://127.0.0.1:6379/0",
        "CELERY_TASK_ALWAYS_EAGER": "false",
        "TRACING_ENABLED": "false",
        "TRACING_EXPORTER_OTLP_ENDPOINT": "",
    }


def is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.strip()
    if not normalized:
        return True
    return normalized.startswith("<") and normalized.endswith(">")


def validate_remote_compose_env(values: dict[str, str]) -> list[str]:
    errors = _validate_required(values, REMOTE_COMPOSE_REQUIRED_KEYS)
    for key in ("SUPABASE_URL", "SUPABASE_DB_URL", "SUPABASE_JWKS_URL"):
        candidate = values.get(key, "")
        if any(token in candidate for token in ("host.docker.internal", "127.0.0.1", "localhost:54321", "localhost:54322")):
            errors.append(f"{key} must target remote Supabase in remote-compose mode.")
    return errors


def validate_local_supabase_compose_env(values: dict[str, str]) -> list[str]:
    errors = _validate_required(values, LOCAL_SUPABASE_REQUIRED_KEYS)
    for key in ("SUPABASE_URL", "SUPABASE_DB_URL", "SUPABASE_JWKS_URL"):
        candidate = values.get(key, "")
        if "host.docker.internal" not in candidate:
            errors.append(f"{key} must use host.docker.internal in local-supabase-compose mode.")
    return errors


def validate_local_supabase_host_env(values: dict[str, str]) -> list[str]:
    errors = _validate_required(values, LOCAL_SUPABASE_REQUIRED_KEYS)
    for key in ("SUPABASE_URL", "SUPABASE_DB_URL", "SUPABASE_JWKS_URL"):
        candidate = values.get(key, "")
        if "127.0.0.1" not in candidate:
            errors.append(f"{key} must use 127.0.0.1 in local-supabase-host mode.")
    return errors


def _validate_required(values: dict[str, str], required_keys: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for key in required_keys:
        value = values.get(key)
        if is_placeholder(value):
            errors.append(f"{key} is missing or still set to a placeholder value.")
    return errors
