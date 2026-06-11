from __future__ import annotations

from scripts.runtime_env import (
    compose_local_supabase_overrides,
    host_local_supabase_overrides,
    parse_env_lines,
    validate_local_supabase_compose_env,
    validate_remote_compose_env,
)


def test_parse_env_lines_strips_quotes() -> None:
    values = parse_env_lines('API_URL="http://127.0.0.1:54321"\nANON_KEY=test-key\n')

    assert values == {
        "API_URL": "http://127.0.0.1:54321",
        "ANON_KEY": "test-key",
    }


def test_compose_local_supabase_overrides_rewrite_hostnames() -> None:
    overrides = compose_local_supabase_overrides(
        {
            "API_URL": "http://127.0.0.1:54321",
            "DB_URL": "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
            "ANON_KEY": "anon",
            "SERVICE_ROLE_KEY": "service",
        }
    )

    assert overrides["SUPABASE_URL"] == "http://host.docker.internal:54321"
    assert overrides["SUPABASE_DB_URL"] == "postgresql://host.docker.internal:54322/postgres"
    assert validate_local_supabase_compose_env(overrides) == []


def test_host_local_supabase_overrides_rewrite_hostnames() -> None:
    overrides = host_local_supabase_overrides(
        {
            "API_URL": "http://localhost:54321",
            "DB_URL": "postgresql://postgres:postgres@localhost:54322/postgres",
            "ANON_KEY": "anon",
            "SERVICE_ROLE_KEY": "service",
        }
    )

    assert overrides["SUPABASE_URL"] == "http://127.0.0.1:54321"
    assert overrides["SUPABASE_DB_URL"] == "postgresql://127.0.0.1:54322/postgres"


def test_validate_remote_compose_env_rejects_local_supabase_urls() -> None:
    errors = validate_remote_compose_env(
        {
            "SUPABASE_DB_URL": "postgresql://host.docker.internal:54322/postgres",
            "SUPABASE_JWKS_URL": "http://host.docker.internal:54321/auth/v1/.well-known/jwks.json",
            "SUPABASE_URL": "http://host.docker.internal:54321",
            "SUPABASE_ANON_KEY": "anon",
            "SUPABASE_SERVICE_ROLE_KEY": "service",
            "SUPABASE_RAW_DOCUMENTS_BUCKET": "raw-documents",
            "SUPABASE_PROCESSED_DOCUMENTS_BUCKET": "processed-documents",
            "SUPABASE_VOICE_BUCKET": "voice-artifacts",
            "REDIS_URL": "redis://redis:6379/0",
            "CELERY_BROKER_URL": "redis://redis:6379/0",
            "CELERY_RESULT_BACKEND": "redis://redis:6379/0",
        }
    )

    assert any("SUPABASE_URL" in error for error in errors)
    assert any("SUPABASE_DB_URL" in error for error in errors)


def test_validate_remote_compose_env_accepts_remote_supabase_urls() -> None:
    errors = validate_remote_compose_env(
        {
            "SUPABASE_DB_URL": "postgresql://user:secret@db.example.supabase.co:5432/postgres",
            "SUPABASE_JWKS_URL": "https://example.supabase.co/auth/v1/.well-known/jwks.json",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "anon",
            "SUPABASE_SERVICE_ROLE_KEY": "service",
            "SUPABASE_RAW_DOCUMENTS_BUCKET": "raw-documents",
            "SUPABASE_PROCESSED_DOCUMENTS_BUCKET": "processed-documents",
            "SUPABASE_VOICE_BUCKET": "voice-artifacts",
            "REDIS_URL": "redis://redis:6379/0",
            "CELERY_BROKER_URL": "redis://redis:6379/0",
            "CELERY_RESULT_BACKEND": "redis://redis:6379/0",
        }
    )

    assert errors == []
