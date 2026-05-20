from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "multi-model-rag"
    environment: str = "development"
    log_level: str = "INFO"
    allow_dev_api_key: bool = Field(default=True, validation_alias=AliasChoices("ALLOW_DEV_API_KEY"))
    internal_service_token: str | None = Field(default=None, validation_alias=AliasChoices("INTERNAL_SERVICE_TOKEN"))

    api_key: str = Field(default="dev-api-key-change-me", min_length=8)
    dev_user_id: str = "00000000-0000-0000-0000-000000000001"
    dev_user_email: str = "dev@example.com"

    supabase_db_url: str | None = Field(default=None, validation_alias=AliasChoices("SUPABASE_DB_URL"))
    supabase_jwks_url: AnyHttpUrl | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_JWKS_URL"),
    )
    supabase_jwt_algorithm: str = "ES256"
    supabase_jwt_audience: str = "authenticated"
    supabase_storage_url: AnyHttpUrl | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_STORAGE_URL", "SUPABASE_URL"),
    )
    supabase_storage_service_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_STORAGE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )
    supabase_auth_public_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SUPABASE_AUTH_PUBLIC_KEY",
            "SUPABASE_PUBLISHABLE_KEY",
            "SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        ),
    )
    supabase_raw_bucket: str = Field(
        default="raw-documents",
        validation_alias=AliasChoices("SUPABASE_RAW_BUCKET", "SUPABASE_RAW_DOCUMENTS_BUCKET"),
    )
    supabase_processed_bucket: str = Field(
        default="processed-documents",
        validation_alias=AliasChoices("SUPABASE_PROCESSED_BUCKET", "SUPABASE_PROCESSED_DOCUMENTS_BUCKET"),
    )
    supabase_voice_bucket: str = Field(
        default="voice-artifacts",
        validation_alias=AliasChoices("SUPABASE_VOICE_BUCKET"),
    )

    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias=AliasChoices("REDIS_URL"))
    celery_broker_url: str | None = Field(default=None, validation_alias=AliasChoices("CELERY_BROKER_URL"))
    celery_result_backend: str | None = Field(default=None, validation_alias=AliasChoices("CELERY_RESULT_BACKEND"))
    celery_task_always_eager: bool = Field(default=True, validation_alias=AliasChoices("CELERY_TASK_ALWAYS_EAGER"))
    celery_max_retries: int = 3
    celery_retry_backoff_seconds: int = 30
    request_timeout_seconds: float = 120.0
    max_request_body_bytes: int = 10_485_760

    groq_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GROQ_API_KEY"))
    groq_base_url: AnyHttpUrl = "https://api.groq.com/openai/v1"
    groq_model_fast: str = "llama-3.1-8b-instant"
    groq_model_balanced: str = Field(
        default="llama-3.3-70b-versatile",
        validation_alias=AliasChoices("GROQ_MODEL_BALANCED", "GROQ_CHAT_MODEL"),
    )
    groq_model_reasoning: str = "deepseek-r1-distill-llama-70b"

    openai_api_key: str | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY"))
    openai_base_url: AnyHttpUrl = "https://api.openai.com/v1"
    openai_model_fast: str = "gpt-4o-mini"
    openai_model_balanced: str = "gpt-4.1-mini"
    openai_model_embedding: str = "text-embedding-3-small"
    openai_model_transcription: str = "gpt-4o-mini-transcribe"
    openai_model_tts: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"

    anthropic_api_key: str | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
    anthropic_base_url: AnyHttpUrl = "https://api.anthropic.com/v1"
    anthropic_model_fast: str = "claude-3-5-haiku-latest"
    anthropic_model_balanced: str = "claude-3-5-sonnet-latest"
    anthropic_model_reasoning: str = "claude-3-7-sonnet-latest"

    ollama_base_url: AnyHttpUrl = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL"),
    )
    ollama_model_local: str = "llama3.1:8b"

    hf_api_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("HF_API_TOKEN", "HUGGINGFACE_API_KEY"),
    )
    hf_embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        validation_alias=AliasChoices(
            "HF_EMBEDDING_MODEL",
            "HUGGINGFACE_EMBEDDING_MODEL",
            "DEFAULT_EMBEDDING_MODEL",
        ),
    )
    hf_base_url: AnyHttpUrl = Field(
        default="https://api-inference.huggingface.co/models",
        validation_alias=AliasChoices("HF_BASE_URL", "HUGGINGFACE_EMBEDDING_URL"),
    )

    chat_profile_fast_chain: str = ""
    chat_profile_balanced_chain: str = ""
    chat_profile_reasoning_chain: str = ""
    chat_profile_local_chain: str = ""
    embedding_profile_chain: str = ""

    chat_profile_fast_timeout_seconds: float = 45.0
    chat_profile_balanced_timeout_seconds: float = 60.0
    chat_profile_reasoning_timeout_seconds: float = 90.0
    chat_profile_local_timeout_seconds: float = 90.0
    embedding_profile_timeout_seconds: float = 60.0

    chat_profile_fast_max_output_tokens: int = 512
    chat_profile_balanced_max_output_tokens: int = 768
    chat_profile_reasoning_max_output_tokens: int = 1024
    chat_profile_local_max_output_tokens: int = 768
    embedding_profile_max_output_tokens: int = 1

    chat_profile_fast_retry_count: int = 1
    chat_profile_balanced_retry_count: int = 1
    chat_profile_reasoning_retry_count: int = 2
    chat_profile_local_retry_count: int = 1
    embedding_profile_retry_count: int = 1

    retryable_status_codes: str = "408,409,425,429,500,502,503,504"

    chunk_size: int = 900
    chunk_overlap: int = 120
    max_context_chunks: int = 8
    max_output_tokens: int = 512
    chunking_version: str = "recursive-v1"
    prompt_version: str = "grounded-v1"
    embedding_dimension: int = 384
    retrieval_vector_candidate_count: int = 24
    retrieval_fts_candidate_count: int = 24
    retrieval_fusion_rank_constant: int = 60
    retrieval_vector_weight: float = 1.0
    retrieval_fts_weight: float = 0.85
    retrieval_max_chunks_per_document: int = 2
    retrieval_context_token_budget: int = 2200
    retrieval_dedup_similarity_threshold: float = 0.92
    retrieval_low_score_threshold: float = 0.018
    retrieval_low_diversity_threshold: int = 2
    retrieval_config_version: str = "hybrid-v1"
    retrieval_sensitivity_ceiling: str | None = None
    reranker_enabled: bool = False
    reranker_model_name: str | None = None
    reranker_top_n: int = 10
    ingestion_inline_text_sync: bool = True
    ingestion_min_text_length: int = 20
    ingestion_allow_small_text: bool = False
    parser_version: str = "parser-v1"
    connector_framework_version: str = "connector-v1"
    voice_enabled: bool = True
    voice_tts_enabled: bool = True
    voice_store_raw_input_audio: bool = False
    voice_signed_url_ttl_seconds: int = 3600
    voice_stt_provider: str = "openai"
    voice_tts_provider: str = "openai"
    voice_transcription_timeout_seconds: float = 90.0
    voice_tts_timeout_seconds: float = 90.0
    voice_stt_retry_count: int = 1
    voice_tts_retry_count: int = 1
    voice_output_audio_format: str = "mp3"
    restricted_data_allowed_profiles: str = "local"
    restricted_data_allowed_providers: str = "ollama"
    rate_limit_window_seconds: int = 60
    rate_limit_requests_per_window: int = 120
    rate_limit_chat_requests_per_window: int = 30
    rate_limit_reasoning_requests_per_window: int = 10
    telemetry_service_name: str = "multi-model-rag-api"
    tracing_enabled: bool = False
    tracing_exporter_otlp_endpoint: AnyHttpUrl | None = Field(
        default=None,
        validation_alias=AliasChoices("TRACING_EXPORTER_OTLP_ENDPOINT"),
    )
    metrics_enabled: bool = True
    audit_retention_days: int = 90
    feedback_retention_days: int = 180
    evaluation_retention_days: int = 180
    secret_provider: str = "env"
    cors_allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias=AliasChoices("CORS_ALLOWED_ORIGINS"),
    )
    evaluation_dataset_path: str = "tests/fixtures/golden_dataset.json"
    evaluation_max_regression_pct: float = 0.05
    evaluation_latency_threshold_ms: int = 6_000
    evaluation_cost_threshold_usd: float = 2.50

    def database_configured(self) -> bool:
        return bool(self.supabase_db_url)

    def validate_phase1(self) -> None:
        missing = [
            name
            for name, value in {
                "SUPABASE_DB_URL": self.supabase_db_url,
                "SUPABASE_JWKS_URL": self.supabase_jwks_url,
                "GROQ_API_KEY": self.groq_api_key,
                "HF_API_TOKEN": self.hf_api_token,
                "REDIS_URL": self.redis_url,
            }.items()
            if not value
        ]
        if missing:
            missing_list = ", ".join(missing)
            raise ValueError(f"Missing required Phase 1 settings: {missing_list}")
        self.validate_runtime()

    def validate_runtime(self) -> None:
        self.validate_model_gateway()
        if self.environment.lower() != "development" and self.allow_dev_api_key:
            raise ValueError("ALLOW_DEV_API_KEY must be false outside development.")
        if self.environment.lower() != "development" and not self.supabase_jwks_url:
            raise ValueError("SUPABASE_JWKS_URL is required outside development.")
        if self.secret_provider not in {"env"}:
            raise ValueError(f"Unsupported secret provider '{self.secret_provider}'.")
        if self.rate_limit_window_seconds < 1:
            raise ValueError("RATE_LIMIT_WINDOW_SECONDS must be at least 1.")
        if self.metrics_enabled and self.request_timeout_seconds <= 0:
            raise ValueError("REQUEST_TIMEOUT_SECONDS must be greater than zero.")
        if self.tracing_enabled and not self.tracing_exporter_otlp_endpoint:
            raise ValueError("TRACING_EXPORTER_OTLP_ENDPOINT is required when tracing is enabled.")

    def validate_model_gateway(self) -> None:
        active_providers = {target.provider for target in self.iter_active_targets()}
        for provider in sorted(active_providers):
            if provider == "groq" and not self.groq_api_key:
                raise ValueError("Missing required provider configuration: GROQ_API_KEY")
            if provider == "openai" and not self.openai_api_key:
                raise ValueError("Missing required provider configuration: OPENAI_API_KEY")
            if provider == "anthropic" and not self.anthropic_api_key:
                raise ValueError("Missing required provider configuration: ANTHROPIC_API_KEY")
            if provider == "huggingface" and not self.hf_api_token:
                raise ValueError("Missing required provider configuration: HF_API_TOKEN")
        if self.reranker_enabled and not self.reranker_model_name:
            raise ValueError("Missing required retrieval configuration: RERANKER_MODEL_NAME")
        if not self.supabase_storage_url:
            raise ValueError("Missing required storage configuration: SUPABASE_URL")
        if not self.supabase_storage_service_key:
            raise ValueError("Missing required storage configuration: SUPABASE_SERVICE_ROLE_KEY")
        if not self.restricted_profiles_set:
            raise ValueError("At least one restricted data profile must be configured.")
        if not self.restricted_provider_set:
            raise ValueError("At least one restricted data provider must be configured.")

    def iter_active_targets(self) -> list["ProviderTarget"]:
        active: list[ProviderTarget] = []
        for profile in ("fast", "balanced", "reasoning", "local", "embedding"):
            active.extend(self.profile_targets(profile))
        return active

    def profile_targets(self, profile: str) -> list["ProviderTarget"]:
        raw = self._profile_chain(profile)
        targets = [_parse_provider_target(item) for item in raw.split("|") if item.strip()]
        if not targets:
            raise ValueError(f"No provider chain configured for profile '{profile}'.")
        return targets

    def profile_timeout_seconds(self, profile: str) -> float:
        return {
            "fast": self.chat_profile_fast_timeout_seconds,
            "balanced": self.chat_profile_balanced_timeout_seconds,
            "reasoning": self.chat_profile_reasoning_timeout_seconds,
            "local": self.chat_profile_local_timeout_seconds,
            "embedding": self.embedding_profile_timeout_seconds,
        }[profile]

    def profile_max_output_tokens(self, profile: str) -> int:
        return {
            "fast": self.chat_profile_fast_max_output_tokens,
            "balanced": self.chat_profile_balanced_max_output_tokens,
            "reasoning": self.chat_profile_reasoning_max_output_tokens,
            "local": self.chat_profile_local_max_output_tokens,
            "embedding": self.embedding_profile_max_output_tokens,
        }[profile]

    def profile_retry_count(self, profile: str) -> int:
        return {
            "fast": self.chat_profile_fast_retry_count,
            "balanced": self.chat_profile_balanced_retry_count,
            "reasoning": self.chat_profile_reasoning_retry_count,
            "local": self.chat_profile_local_retry_count,
            "embedding": self.embedding_profile_retry_count,
        }[profile]

    def parsed_retryable_status_codes(self) -> tuple[int, ...]:
        return tuple(
            int(code.strip())
            for code in self.retryable_status_codes.split(",")
            if code.strip()
        )

    def _profile_chain(self, profile: str) -> str:
        fast_defaults = [f"groq:{self.groq_model_fast}"]
        balanced_defaults = [f"groq:{self.groq_model_balanced}"]
        reasoning_defaults = [f"groq:{self.groq_model_reasoning}"]
        local_defaults = [f"ollama:{self.ollama_model_local}"]
        embedding_defaults = [f"huggingface:{self.hf_embedding_model}"]
        if self.openai_api_key:
            fast_defaults.append(f"openai:{self.openai_model_fast}")
            balanced_defaults.append(f"openai:{self.openai_model_balanced}")
            reasoning_defaults.append(f"openai:{self.openai_model_balanced}")
            embedding_defaults.append(f"openai:{self.openai_model_embedding}")
        if self.anthropic_api_key:
            fast_defaults.append(f"anthropic:{self.anthropic_model_fast}")
            balanced_defaults.append(f"anthropic:{self.anthropic_model_balanced}")
            reasoning_defaults.append(f"anthropic:{self.anthropic_model_reasoning}")
        if self.groq_api_key:
            local_defaults.append(f"groq:{self.groq_model_fast}")
        if self.openai_api_key:
            local_defaults.append(f"openai:{self.openai_model_fast}")
        defaults = {
            "fast": "|".join(fast_defaults),
            "balanced": "|".join(balanced_defaults),
            "reasoning": "|".join(reasoning_defaults),
            "local": "|".join(local_defaults),
            "embedding": "|".join(embedding_defaults),
        }
        configured = {
            "fast": self.chat_profile_fast_chain,
            "balanced": self.chat_profile_balanced_chain,
            "reasoning": self.chat_profile_reasoning_chain,
            "local": self.chat_profile_local_chain,
            "embedding": self.embedding_profile_chain,
        }[profile]
        return configured or defaults[profile]

    @property
    def restricted_profiles_set(self) -> set[str]:
        return {item.strip() for item in self.restricted_data_allowed_profiles.split(",") if item.strip()}

    @property
    def restricted_provider_set(self) -> set[str]:
        return {item.strip() for item in self.restricted_data_allowed_providers.split(",") if item.strip()}

    @property
    def dev_api_key_enabled(self) -> bool:
        return self.environment.lower() == "development" or self.allow_dev_api_key

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]

    @property
    def supabase_auth_base_url(self) -> str | None:
        if not self.supabase_storage_url:
            return None
        return f"{str(self.supabase_storage_url).rstrip('/')}/auth/v1"

    @property
    def effective_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def effective_celery_result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


class ProviderTarget(tuple):
    provider: str
    model_name: str

    def __new__(cls, provider: str, model_name: str):
        return super().__new__(cls, (provider, model_name))

    @property
    def provider(self) -> str:
        return self[0]

    @property
    def model_name(self) -> str:
        return self[1]


def _parse_provider_target(value: str) -> ProviderTarget:
    try:
        provider, model_name = value.split(":", 1)
    except ValueError as exc:
        raise ValueError(f"Invalid provider target '{value}'. Expected provider:model.") from exc
    provider_name = provider.strip().lower()
    model = model_name.strip()
    if provider_name not in {"groq", "openai", "anthropic", "ollama", "huggingface"}:
        raise ValueError(f"Unsupported provider '{provider_name}' in profile chain.")
    if not model:
        raise ValueError(f"Missing model name in provider target '{value}'.")
    return ProviderTarget(provider_name, model)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
