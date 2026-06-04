# Multi-Model RAG

Multi-Model RAG is a FastAPI backend for a workspace-resolved B2C retrieval-augmented generation product. It ingests user-owned content, turns it into searchable chunks, retrieves grounded context with pgvector + PostgreSQL full-text search, and answers questions through text and voice APIs.

The current product scope is:

- document ingestion and grounded chat
- audio ingestion and voice chat
- workspace-resolved access control
- feedback, evaluation, observability, and operational tooling

It does not currently include a video pipeline.

## What This Project Does

At a high level, the backend supports this flow:

1. A user authenticates with either a development API key or a Supabase JWT.
2. The backend resolves that user to a personal workspace.
3. The user uploads text, files, or audio.
4. The ingestion pipeline parses the source, normalizes it, chunks it, embeds it, and stores searchable records in Postgres.
5. Chat or voice requests retrieve relevant chunks from the user’s workspace.
6. The answer generator produces a grounded response with source citations.
7. Feedback, telemetry, and evaluation tooling help validate retrieval quality and runtime behavior.

## Core Capabilities

### API surface

The public API is exposed through FastAPI and includes:

- health endpoints: `/health`, `/ready`, `/metrics`
- auth routes
- documents routes
- audio routes
- chat routes
- voice routes
- conversation routes
- feedback routes

The main route modules live in:

- [app/api/routes/auth.py](app/api/routes/auth.py)
- [app/api/routes/documents.py](app/api/routes/documents.py)
- [app/api/routes/audio.py](app/api/routes/audio.py)
- [app/api/routes/chat.py](app/api/routes/chat.py)
- [app/api/routes/voice.py](app/api/routes/voice.py)
- [app/api/routes/conversations.py](app/api/routes/conversations.py)
- [app/api/routes/feedback.py](app/api/routes/feedback.py)
- [app/api/routes/health.py](app/api/routes/health.py)

### Document ingestion

The document pipeline supports:

- inline text documents
- Markdown
- PDF
- DOCX
- HTML
- audio-backed document parsing

The ingestion path is mostly shared after parsing:

1. create a document record
2. create an ingestion job
3. load raw text or bytes
4. parse by source type
5. normalize into extracted blocks
6. chunk the extracted content
7. generate embeddings
8. store chunks, structure metadata, and searchable vectors

Main files:

- [app/services/document_service.py](app/services/document_service.py)
- [app/services/ingestion_service.py](app/services/ingestion_service.py)
- [app/ingestion/registry.py](app/ingestion/registry.py)
- [app/ingestion/chunking.py](app/ingestion/chunking.py)
- [app/storage/repositories/ingestion.py](app/storage/repositories/ingestion.py)

### Retrieval and grounded chat

Retrieval is built on:

- pgvector similarity search
- PostgreSQL full-text search
- hybrid candidate fusion
- chunk deduplication
- structural chunk context
- optional heuristic reranking

Chat then uses the selected retrieval context to produce a grounded answer with citations.

Main files:

- [app/retrieval/retriever.py](app/retrieval/retriever.py)
- [app/retrieval/reranker.py](app/retrieval/reranker.py)
- [app/services/chat_service.py](app/services/chat_service.py)
- [app/storage/repositories/retrieval.py](app/storage/repositories/retrieval.py)

### Audio and voice

The backend supports both audio ingestion and live voice chat flows.

Voice features include:

- audio upload handling
- transcription
- chat over the transcribed request
- text-to-speech output
- fallback to text-only when TTS fails

Main files:

- [app/api/routes/audio.py](app/api/routes/audio.py)
- [app/api/routes/voice.py](app/api/routes/voice.py)
- [app/voice/](app/voice)
- [app/services/voice_chat_service.py](app/services/voice_chat_service.py)

### Model routing

The project is designed to work across multiple providers and profiles.

Supported provider integrations in the current codebase:

- Groq
- OpenAI
- Anthropic
- Ollama
- Hugging Face embeddings

Supported chat profiles:

- `fast`
- `balanced`
- `reasoning`
- `local`

The profile chain system lets you define fallback provider/model sequences per profile.

Main files:

- [app/llm/router.py](app/llm/router.py)
- [app/core/config.py](app/core/config.py)

### Security and access control

The backend is workspace-resolved rather than tenant-path-based. Identity is used to resolve a personal workspace, and most data access is scoped through workspace ownership plus user ownership checks.

Security-related behavior includes:

- development API key authentication
- Supabase JWT authentication
- workspace resolution
- request correlation IDs
- request-size limits
- per-route rate limiting
- restricted-data provider/profile policy hooks

Main files:

- [app/security/auth.py](app/security/auth.py)
- [app/security/rate_limit.py](app/security/rate_limit.py)
- [app/security/policy.py](app/security/policy.py)
- [app/api/dependencies.py](app/api/dependencies.py)

### Evaluation and operational tooling

The repo also includes internal tooling for:

- retrieval evaluation with a golden dataset
- readiness and hardening reports
- tracing the RAG pipeline
- local load probing
- dead-letter queue recovery helpers

Main files:

- [app/services/evaluation_service.py](app/services/evaluation_service.py)
- [app/evaluation/runner.py](app/evaluation/runner.py)
- [scripts/run_evaluation.py](scripts/run_evaluation.py)
- [scripts/trace_rag_pipeline.py](scripts/trace_rag_pipeline.py)
- [scripts/run_local_load_probe.py](scripts/run_local_load_probe.py)
- [scripts/requeue_dead_letter_job.py](scripts/requeue_dead_letter_job.py)

## Architecture Overview

The project is organized as a service-oriented backend:

- `app/api`
  - FastAPI routes, schemas, dependencies, and error handling
- `app/core`
  - configuration, DI container, middleware, logging, telemetry, runtime setup
- `app/domain`
  - core entities and domain errors
- `app/evaluation`
  - dataset loading and evaluation runner logic
- `app/ingestion`
  - parsers, extraction models, and chunking logic
- `app/llm`
  - provider clients and routing logic
- `app/retrieval`
  - retrieval, reranking, and retrieval utilities
- `app/security`
  - auth, rate limiting, and data-policy enforcement
- `app/services`
  - application-level orchestration services
- `app/storage`
  - database session logic, migrations, models, and repositories
- `app/voice`
  - voice-specific helpers and media handling
- `app/workers`
  - background task wiring

The application entrypoint is [app/main.py](app/main.py).

## Request and Data Flow

### Text/document flow

1. `POST /v1/documents` creates an inline-text document, or `POST /v1/documents/upload-url` prepares a storage upload.
2. A document row and ingestion job row are created.
3. The ingestion service parses and normalizes the content.
4. The chunker creates parent/child searchable chunks.
5. Embeddings are generated and stored.
6. `POST /v1/chat` retrieves relevant chunks and returns a grounded answer.

### Voice flow

1. `POST /v1/voice/chat` accepts voice metadata plus optional uploaded audio.
2. Audio is transcribed through the configured STT provider.
3. The transcribed query flows through the same chat/retrieval path.
4. If TTS is enabled and succeeds, the response includes audio output metadata.
5. If TTS fails, the API can fall back to text-only behavior.

## Storage Model

The backend expects:

- PostgreSQL with pgvector
- Redis for rate limiting and Celery-backed async work
- Supabase Storage-compatible buckets for raw and processed artifacts

The SQL migration files live in:

- [app/storage/db/migrations](app/storage/db/migrations)

Important notes:

- database bootstrap and migration application are handled during startup when the DB is configured
- the latest workspace-scoped evaluation migration is `0011_workspace_evaluation_runs.sql`

## Local Development

### Requirements

- Python `3.11+`
- PostgreSQL with pgvector
- Redis
- Supabase-compatible storage configuration
- at least one working chat provider and one embedding provider

Optional but useful:

- Docker Desktop
- Prometheus
- Ollama for local profile testing

### Environment setup

Copy the example environment file:

```bash
cp .env.example .env
```

Important variables you will usually need to set:

- `SUPABASE_DB_URL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `REDIS_URL`
- one or more provider API keys such as `GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `HF_API_TOKEN`

Key environment groups:

- app/runtime settings
- Supabase/Postgres/storage settings
- Redis/Celery settings
- provider/model settings
- retrieval/chunking settings
- voice settings
- security/rate-limit settings
- observability settings

See [.env.example](.env.example) and [app/core/config.py](app/core/config.py) for the full list.

### Run with Docker Compose

The included Compose file starts:

- the API
- Redis
- Prometheus

```bash
docker compose up --build
```

Open:

- API docs: `http://localhost:8000/docs`
- health: `http://localhost:8000/health`
- readiness: `http://localhost:8000/ready`
- metrics: `http://localhost:8000/metrics`
- Prometheus: `http://localhost:9090`

Important: the compose file does not currently provision Postgres/pgvector for you. You still need a reachable database configured through `SUPABASE_DB_URL`.

### Run locally without Docker

Unix-like shells:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

### Local pgvector database example

If you want a disposable local pgvector database for development or tests, a simple Docker option is:

```bash
docker run -d --name mmrag-pg \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=postgres \
  -p 54329:5432 \
  pgvector/pgvector:pg17
```

Then point `SUPABASE_DB_URL` at that instance.

## Authentication Model

### Development

In development, the backend can authenticate requests using:

- `X-API-Key`

That dev identity resolves to the configured personal workspace.

### Production-shaped flow

In production-style setups, the backend expects:

- Supabase-issued JWTs in the `Authorization: Bearer ...` header

The system then:

1. validates the JWT
2. extracts the user identity
3. resolves the user’s workspace
4. applies route-level rate limiting and access rules

## Example API calls

Create an inline text document:

```bash
curl -X POST http://localhost:8000/v1/documents \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "title":"Employee Handbook",
    "source_type":"text",
    "text":"Remote work is allowed three days per week with manager approval.",
    "metadata":{"department":"hr"},
    "sensitivity":"internal"
  }'
```

Ask a grounded chat question:

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "query":"What is the remote work policy?",
    "profile":"balanced"
  }'
```

Submit message feedback:

```bash
curl -X POST http://localhost:8000/v1/messages/<message-id>/feedback \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "rating":1,
    "comment":"Correct and useful.",
    "categories":["helpful_sources"]
  }'
```

Run a retrieval evaluation:

```bash
python scripts/run_evaluation.py --workspace-id 11111111-1111-1111-1111-111111111111
```

## Background execution model

The project uses Celery + Redis for background-capable ingestion flows, but local development is configured to be simpler by default:

- `CELERY_TASK_ALWAYS_EAGER=true` in `.env.example`

That means many ingestion flows can run synchronously during development unless you explicitly configure a broker/backend for full async behavior.

## Testing

The repo includes multiple test layers:

- `tests/unit`
- `tests/service`
- `tests/api`
- `tests/regression`
- `tests/integration`

Typical local test run:

```bash
pytest tests -q
```

There are also more specialized assets and workflows in:

- `tests/evaluation`
- `tests/fixtures`
- `tests/manual`

## Scripts and utility commands

Notable scripts:

- `scripts/run_evaluation.py`
  - runs retrieval evaluation and persists a workspace-scoped evaluation run
- `scripts/trace_rag_pipeline.py`
  - traces retrieval and answer assembly behavior
- `scripts/run_local_load_probe.py`
  - runs a lightweight local chat/load probe
- `scripts/requeue_dead_letter_job.py`
  - requeues failed async work
- `scripts/export_usage_report.py`
  - exports usage-oriented reporting data

## Operational endpoints

- `GET /health`
  - liveness-style health signal
- `GET /ready`
  - dependency readiness signal
- `GET /metrics`
  - Prometheus metrics endpoint

## Important project scope notes

- this is a backend-focused codebase
- it is optimized around workspace-resolved B2C flows, not tenant-path enterprise admin surfaces
- chat streaming is not currently exposed in the public API
- video ingestion/retrieval is not currently implemented
- usage export and admin reporting are not the main product focus


## Summary

This repository is a multi-provider RAG backend with:

- shared ingestion and retrieval infrastructure
- grounded text and voice interactions
- workspace-scoped security boundaries
- operational tooling for evaluation, observability, and runtime validation

If you want to understand the codebase quickly, the best starting path is:

1. [app/main.py](app/main.py)
2. [app/core/container.py](app/core/container.py)
3. [app/api/routes](app/api/routes)
4. [app/services](app/services)
5. [app/storage/db/migrations](app/storage/db/migrations)
