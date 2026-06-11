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
- Supabase Auth and Storage-compatible services for identity and object artifacts

The SQL migration files live in:

- [app/storage/db/migrations](app/storage/db/migrations)

Important notes:

- database bootstrap and migration application are handled during startup when the DB is configured
- the latest workspace-scoped evaluation migration is `0011_workspace_evaluation_runs.sql`

## Local Development

### Requirements

- Python `3.11+`
- Docker Desktop
- at least one working chat provider and one embedding provider

Optional but useful:

- Prometheus
- Supabase CLI for the optional local-Supabase flow
- Ollama for local profile testing

### Environment setup

Choose the env template that matches how you want to run the backend.

```bash
cp .env.example .env
cp .env.compose.example .env.compose
cp .env.compose.dev.example .env.compose.dev
```

Use:

- `.env.example`
  - app runs on your host machine against your remote Supabase project
- `.env.compose.example`
  - app runs in Docker Compose against your remote Supabase project
- `.env.compose.dev.example`
  - app runs in Docker Compose dev mode against your remote Supabase project with live reload
- `.env.host.local-supabase.example`
  - optional host-run app flow against `supabase start`
- `.env.compose.local-supabase.example`
  - optional Docker Compose flow against `supabase start`
- `.env.production.app.example`
  - contract for Kubernetes or other production container deployments

Important variables you will usually need to set:

- `SUPABASE_DB_URL`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
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

See [.env.example](.env.example), [.env.compose.example](.env.compose.example), [.env.compose.dev.example](.env.compose.dev.example), [.env.host.local-supabase.example](.env.host.local-supabase.example), [.env.compose.local-supabase.example](.env.compose.local-supabase.example), [.env.production.app.example](.env.production.app.example), and [app/core/config.py](app/core/config.py) for the full list.

### Run with Docker Compose

The default production-shaped Docker path keeps DB/Auth/Storage remote and only runs the app tier plus local support services:

- the API
- the Celery worker
- Redis
- Redis exporter
- OpenTelemetry collector
- Prometheus
- Grafana

```bash
cp .env.compose.example .env.compose
./scripts/bootstrap_compose_remote.sh
```

PowerShell:

```powershell
Copy-Item .env.compose.example .env.compose
.\scripts\bootstrap_compose_remote.ps1
```

Open:

- API docs: `http://localhost:8000/docs`
- health: `http://localhost:8000/health`
- readiness: `http://localhost:8000/ready`
- metrics: `http://localhost:8000/metrics`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001`

The default bootstrap script:

1. validates `.env.compose`
2. validates the Compose configuration
3. starts the app-side Compose services
4. waits for readiness
5. verifies database bootstrap and migration state against the remote Supabase project

### Run with Docker Compose dev workflow

The dev Docker path keeps the same remote-Supabase contract and full local support stack, but mounts source code into the `api` and `worker` containers so normal Python edits reload without rebuilding.

```bash
cp .env.compose.dev.example .env.compose.dev
./scripts/bootstrap_compose_dev_remote.sh
```

PowerShell:

```powershell
Copy-Item .env.compose.dev.example .env.compose.dev
.\scripts\bootstrap_compose_dev_remote.ps1
```

The dev bootstrap script:

1. validates `.env.compose.dev`
2. validates the layered Compose configuration
3. starts the full dev stack with `docker-compose.yml` plus `docker-compose.dev.yml`
4. waits for readiness
5. verifies database bootstrap against the remote Supabase project

Normal source edits to `app/` and `scripts/` should reload the API and restart the worker automatically. Rebuilds are still required when dependencies, Dockerfile stages, or env contracts change.

### Optional local Supabase mode

Use this mode only if you want a self-contained local DB/Auth/Storage stack.

Unix-like shells:

```bash
python scripts/generate_local_supabase_env.py compose .env.compose.local-supabase
./scripts/bootstrap_local_supabase_stack.sh
```

PowerShell:

```powershell
python scripts/generate_local_supabase_env.py compose .env.compose.local-supabase
.\scripts\bootstrap_local_supabase_stack.ps1
```

This optional path:

1. starts `supabase start`
2. generates a local-Supabase-targeted env file
3. bootstraps required storage buckets
4. starts the same app-side Compose services
5. verifies readiness and migration state

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

For host-run development, use `.env` with your remote Supabase values.

### Optional host + local Supabase example

If you want to run the backend directly on your host against `supabase start` instead of a remote project:

```bash
supabase start
python scripts/generate_local_supabase_env.py host .env.host.local-supabase
source .venv/bin/activate
uvicorn app.main:app --reload
```

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

The project uses Celery + Redis for background-capable ingestion flows.

Production-shaped local container runs use:

- dedicated `api` and `worker` services
- `CELERY_TASK_ALWAYS_EAGER=false`
- a slim API image target and a heavier worker image target built from the same Dockerfile

The separate dev Docker workflow keeps the same full stack, but swaps in:

- `api-dev-runtime` with mounted source + `uvicorn --reload`
- `worker-dev-runtime` with mounted source + a file watcher that restarts Celery on Python changes

Host-only development can still choose eager execution by adjusting env values when needed.

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

## Container Platform Assets

Container and deployment assets now live under `infra/`:

- [infra/CONTAINER_PLATFORM.md](infra/CONTAINER_PLATFORM.md)
- [infra/prometheus](infra/prometheus)
- [infra/grafana](infra/grafana)
- [infra/otel](infra/otel)
- [infra/k8s](infra/k8s)


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
