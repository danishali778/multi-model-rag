# Multi-Model RAG

Enterprise-ready Retrieval Augmented Generation backend with tenant-scoped APIs, Supabase-backed storage, pgvector retrieval, and model/provider boundaries aligned to the planning docs.

## What Is Included

- FastAPI service with `/health`, `/ready`, `/metrics`, tenant listing, documents, chat, conversations, feedback, and admin/ops endpoints
- Multi-provider model gateway with `Groq`, `OpenAI`, `Anthropic`, `Ollama`, and hosted embedding provider routing
- Supabase-backed pgvector + Postgres FTS retrieval with ACL-aware filtering, reranker hooks, and retrieval telemetry
- Async ingestion with `Celery + Redis`, signed Supabase Storage uploads, and parsers for text, Markdown, PDF, DOCX, and HTML
- Request correlation IDs, structured logging, JWT-first auth posture, rate limiting, restricted-data provider policy hooks, and redacted audit logging
- Offline evaluation scaffolding with golden dataset loading and persisted evaluation runs
- Docker Compose for API, Redis, and Prometheus; Supabase should provide database, auth, storage, and pgvector
- Supabase-aligned SQL migrations under `app/storage/db/migrations`
- Unit coverage for routing, config, auth, parsers, retrieval, rate limiting, and evaluation helpers

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- API health: `http://localhost:8000/health`
- API readiness: `http://localhost:8000/ready`
- API docs: `http://localhost:8000/docs`
- Supabase: use a local Supabase stack or a dedicated Supabase project for database, auth, storage, and vectors

Apply the SQL migrations in `app/storage/db/migrations` to your Supabase/Postgres database before using the APIs.

For local development:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Example Requests

Ingest a document:

```bash
curl -X POST http://localhost:8000/v1/tenants/11111111-1111-1111-1111-111111111111/documents \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"title":"Employee Handbook","source_type":"text","text":"Your enterprise knowledge text...","metadata":{"source":"handbook"},"sensitivity":"internal","acl_group_ids":[]}'
```

Ask a question:

```bash
curl -X POST http://localhost:8000/v1/tenants/11111111-1111-1111-1111-111111111111/chat \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"question":"What does the handbook say?","model_profile":"balanced","top_k":5,"filters":{},"stream":false}'
```

Record feedback:

```bash
curl -X POST http://localhost:8000/v1/tenants/11111111-1111-1111-1111-111111111111/messages/<message-id>/feedback \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"rating":1,"comment":"Correct and useful.","categories":["helpful_sources"]}'
```

Usage summary:

```bash
curl -X GET "http://localhost:8000/v1/tenants/11111111-1111-1111-1111-111111111111/admin/usage?group_by=model_profile" \
  -H "X-API-Key: dev-api-key-change-me"
```

Run an offline evaluation:

```bash
.venv/bin/python scripts/run_evaluation.py --tenant-id 11111111-1111-1111-1111-111111111111
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Operations

- Metrics: `GET /metrics`
- Evaluation runner: `scripts/run_evaluation.py`
- Usage export: `scripts/export_usage_report.py`
- Dead-letter requeue: `scripts/requeue_dead_letter_job.py`

## Remaining Work

- Apply the latest migration `0005_phase56_hardening.sql` to the target Supabase project
- Re-run the live DB-backed integration flow in an environment with network access to Supabase
- Enable OTLP tracing exporter in deployment if you want external trace collection instead of the local fallback
