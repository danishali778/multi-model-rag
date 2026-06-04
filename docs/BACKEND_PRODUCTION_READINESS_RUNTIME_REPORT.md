# Backend Production Readiness Runtime Report

## Status

- Overall recommendation: `NO-GO` for full production signoff in this environment
- Reason: the local runtime/test pass is now strong across mocked, in-process, and local DB-backed behavior, but resilience drills, deeper observability validation, and production-like load evidence remain incomplete

## Runtime Evidence Collected

- Created a Windows-local virtual environment at `.venv.win`
- Installed the backend/test dependencies needed to execute the Python test suite locally
- Ran the full local test suite with runtime execution:
  - `163 passed`
  - `0 skipped`
  - `6 warnings`
- Brought up a disposable local `pgvector` Postgres instance with Docker
- Ran DB-backed end-to-end smoke tests successfully against the local Postgres instance
- Ran live migration integration tests successfully against disposable local databases
- Ran a lightweight local load probe against chat over the real backend stack with mocked model providers:
  - requests: `20`
  - concurrency: `5`
  - status counts: `20 x 200`
  - latency: `p50 876.05ms`, `p95 1005.53ms`, `p99 1007.97ms`

## Issues Confirmed And Fixed In This Pass

### High

- Invalid JWTs could bubble up as raw `PyJWT` exceptions such as `InvalidAudienceError`, which risked turning hostile or malformed bearer tokens into `500` errors instead of `401` responses.
  - Fixed in `app/security/auth.py`
  - Covered by unit and API regression tests

### Medium

- Hybrid graph chunking did not split prose when token count landed exactly on the configured chunk boundary, which broke child-chunk linking expectations and could reduce retrieval continuity.
  - Fixed in `app/ingestion/chunking.py`
  - Covered by the existing chunking test suite and full runtime rerun

- Request-size rejection in middleware escaped as an unhandled exception instead of producing a clean API `400` response with diagnostics.
  - Fixed in `app/core/middleware.py`
  - Covered by API regression tests for oversized requests and correlation ID propagation

- Windows-local async database startup failed because psycopg cannot run with the default `ProactorEventLoop`.
  - Fixed with Windows runtime event-loop policy configuration in `app/core/runtime.py`
  - Covered by DB-backed integration and migration runs in this environment

- Local plain-Postgres migration bootstrap exposed multiple portability/idempotency bugs:
  - missing `extensions` schema creation before `pgvector`
  - unqualified `extensions.vector_cosine_ops` index opclass
  - duplicate connector policy creation in `0004_phase4_ingestion_scale.sql`
  - workspace-era/no-ledger bootstrap still skipping `0011_workspace_evaluation_runs.sql`
  - Fixed in the migration files and `app/storage/db/session.py`
  - Covered by live migration integration tests and DB-backed smoke reruns

- Live retrieval against a plain `pgvector` Postgres failed because the vector distance operator was not schema-qualified.
  - Fixed in `app/storage/repositories/retrieval.py`
  - Covered by the passing DB-backed chat smoke flow

## Validation Coverage By Area

### 1. Auth And Access Control

- `Validated locally`
- Evidence:
  - auth service unit tests pass
  - API auth route tests pass
  - added coverage for wrong audience, invalid signature, missing subject, invalid UUID subject, and protected-route `401` behavior
- Remaining gap:
  - no live database-backed cross-user access matrix was run against a real Postgres/Supabase instance in this environment

### 2. API Validation And Abuse Handling

- `Validated locally`
- Evidence:
  - API, regression, and route tests pass
  - invalid chat/voice profiles, legacy payload rejection, and auth callback validation are covered
  - oversized request rejection is now covered at the middleware boundary
  - rate-limit behavior is covered in unit tests

### 3. Document Ingestion Integration

- `Validated locally`
- Evidence:
  - unit and service coverage passes
  - in-process ingestion behavior is exercised by the existing suite
  - DB-backed end-to-end document ingestion smoke passes against a local `pgvector` Postgres database

### 4. Audio And Voice Integration

- `Validated locally`
- Evidence:
  - API, service, unit, and regression tests pass
  - TTS fallback regression coverage is active again

### 5. Retrieval And Chat Correctness

- `Validated locally`
- Evidence:
  - service, regression, and unit coverage passes
  - conversation continuation, `404` behavior, reranker telemetry, and retrieval evaluation coverage are present

### 6. Migration And Bootstrap Behavior

- `Validated locally`
- Evidence:
  - migration/bootstrap unit tests pass
  - fresh local live bootstrap is covered by integration tests
  - workspace-era/no-ledger `evaluation_runs` recovery is covered by integration tests

### 7. Failure-Mode And Resilience Behavior

- `Partially validated`
- Evidence:
  - provider failure behavior is covered by tests
  - rate limiter memory fallback is covered, including a concurrent in-memory check
  - health/readiness degradation is covered when database, Redis, and model-provider checks fail
- Remaining gap:
  - no live Redis outage, DB disconnect, storage outage, or worker-crash exercise was run end to end

### 8. Load And Scale Behavior

- `Partially validated`
- Evidence:
  - limited local concurrency validation was run against the in-memory rate limiter
  - a local DB-backed load probe completed `20` chat requests at concurrency `5` with `20/20` successful `200` responses
  - observed local latency was approximately `p50 876ms`, `p95 1006ms`, `p99 1008ms`
  - earlier architecture analysis identified likely bottlenecks in chunk persistence, worker startup, DB connections, and retrieval latency
- Remaining gap:
  - the current load probe uses mocked model providers and local in-process execution, so it is not yet a production-like performance signoff

### 9. Observability And Diagnostics

- `Partially validated`
- Evidence:
  - `/health`, `/ready`, and `/metrics` coverage passes
  - metrics exposure is asserted in tests
  - correlation IDs are verified in both validation and app-error responses
  - oversized-request rejection now preserves API error shape and correlation diagnostics
- Remaining gap:
  - structured logs, tracing export, denied-access auditability, and incident-debugging quality were not validated end to end

## Severity-Ranked Open Findings

### High

- Failure-mode coverage is still incomplete for Redis, storage, database degradation, and worker lifecycle disruptions.
  - Impact: production recovery behavior under real partial outages is still not proven.

### Medium

- Load/scaling evidence is stronger than before, but still limited to a local in-process probe with mocked model providers.
  - Impact: p95 latency under real provider/network conditions, DB pressure, queue behavior, and concurrency ceilings are still not fully proven.

- Observability validation is incomplete beyond health/metrics route presence.
  - Impact: on-call diagnosis quality is not yet proven.

### Low

- Windows runtime compatibility now depends on a selector-loop compatibility shim that emits Python `3.14` deprecation warnings for future `3.16` removal.
  - Impact: not a blocker today, but it should be revisited before future Python upgrades.

- The local test run reports a `StarletteDeprecationWarning` around `fastapi.testclient` and `httpx`.
  - Impact: not a functional blocker today, but it should be cleaned up before dependency upgrades force the issue.

## Known Blockers

- Outbound TCP to the configured Supabase/Postgres host is still blocked in this environment, so the validation path relies on a local Docker-backed Postgres instead of the target external database
- Resilience drills against real Redis/storage/provider outages have not yet been executed end to end
- Load validation is still local and mocked at the provider layer

## Recommended Next Steps

1. Run resilience drills for Redis down, DB down, storage failure, provider timeouts, and worker/job interruptions
2. Expand load validation beyond the local mocked-provider probe to a production-like environment with real service dependencies
3. Validate operational diagnostics with real logs/metrics/tracing enabled
4. Revisit the Windows selector-loop compatibility shim before Python `3.16`
5. Clean up the `fastapi.testclient` / `httpx` deprecation path

## Bottom Line

This backend is in much better shape than before this runtime pass:

- the full local test suite now passes, including DB-backed integration and live migration coverage
- multiple real runtime issues were found and fixed across auth, middleware, migrations, retrieval, and Windows-local DB startup
- auth hardening is stronger
- local regression coverage is stronger

But the backend is not yet ready for a full production `GO` decision until broader resilience evidence, production-like load validation, and deeper observability validation are completed.
