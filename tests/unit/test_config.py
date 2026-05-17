import pytest

from app.core.config import Settings


def test_settings_support_existing_env_aliases(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://example")
    monkeypatch.setenv("SUPABASE_JWKS_URL", "https://example.supabase.co/auth/v1/.well-known/jwks.json")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("SUPABASE_RAW_DOCUMENTS_BUCKET", "raw-documents")
    monkeypatch.setenv("SUPABASE_PROCESSED_DOCUMENTS_BUCKET", "processed-documents")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("GROQ_CHAT_MODEL", "groq-model")
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf-key")
    monkeypatch.setenv("HUGGINGFACE_EMBEDDING_MODEL", "sentence-transformers/test-model")
    monkeypatch.setenv("HUGGINGFACE_EMBEDDING_URL", "https://api-inference.huggingface.co/models/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    settings = Settings(_env_file=None)

    assert str(settings.supabase_storage_url) == "https://example.supabase.co/"
    assert settings.supabase_storage_service_key == "service-role"
    assert settings.supabase_raw_bucket == "raw-documents"
    assert settings.supabase_processed_bucket == "processed-documents"
    assert settings.groq_model_balanced == "groq-model"
    assert settings.hf_api_token == "hf-key"
    assert settings.hf_embedding_model == "sentence-transformers/test-model"


def test_validate_phase1_requires_critical_settings():
    settings = Settings(_env_file=None)

    with pytest.raises(ValueError, match="Missing required Phase 1 settings"):
        settings.validate_phase1()


def test_default_active_provider_chains_only_include_configured_providers():
    settings = Settings(
        _env_file=None,
        supabase_db_url="postgresql://example",
        supabase_jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json",
        groq_api_key="groq-key",
        hf_api_token="hf-key",
        redis_url="redis://localhost:6379/0",
    )

    assert [target.provider for target in settings.profile_targets("balanced")] == ["groq"]
    assert [target.provider for target in settings.profile_targets("embedding")] == ["huggingface"]


def test_validate_phase1_requires_reranker_model_name_when_enabled(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://example")
    monkeypatch.setenv("SUPABASE_JWKS_URL", "https://example.supabase.co/auth/v1/.well-known/jwks.json")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("HF_API_TOKEN", "hf-key")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    settings = Settings(_env_file=None, reranker_enabled=True)

    with pytest.raises(ValueError, match="RERANKER_MODEL_NAME"):
        settings.validate_phase1()


def test_validate_runtime_rejects_dev_api_key_in_production(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://example")
    monkeypatch.setenv("SUPABASE_JWKS_URL", "https://example.supabase.co/auth/v1/.well-known/jwks.json")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("HF_API_TOKEN", "hf-key")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    settings = Settings(
        _env_file=None,
        environment="production",
        allow_dev_api_key=True,
    )

    with pytest.raises(ValueError, match="ALLOW_DEV_API_KEY"):
        settings.validate_runtime()
