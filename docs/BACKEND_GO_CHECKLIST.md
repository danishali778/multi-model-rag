# Backend GO Checklist

## Goal

Move this backend from the current evidence-based `NO-GO` state to a production-ready `GO` decision with real infrastructure-backed validation.

## Current Execution Status

- Current recommendation: `NO-GO`
- Backend runtime evidence is materially stronger than the prior pass
- Local DB-backed integration, live migration validation, and a lightweight local load probe have now been executed
- Remaining gaps are concentrated in resilience drills, production-like load depth, and deeper observability validation

## 1. Database-backed Integration

Status: `completed locally`

- Run `tests/integration/end_to_end/test_backend_smoke.py` against a reachable Postgres/Supabase environment
- Confirm document create/list/detail/ingestion/chat/conversation/feedback flows pass end to end
- Record exact pass/fail results
- No skipped DB-backed smoke tests remain

## 2. Live Migration Validation

Status: `completed locally`

- Run migrations on a fresh disposable database
- Run migrations on a workspace-era shaped database if available
- Verify `evaluation_runs` bootstrap behavior in a live DB
- Confirm rerunning migrations is safe and idempotent
- Record exact migration commands and results

## 3. Auth And Access-Control Validation

Status: `completed locally`

- Test invalid JWT signature, wrong audience, expired token, missing subject, and invalid subject UUID
- Test unauthorized access across users/workspaces for documents, ingestion jobs, conversations, sources, and feedback
- Confirm correct `401` / `403` / `404` behavior
- No auth path returns unexpected `5xx`

## 4. API Abuse And Boundary Validation

Status: `completed locally`

- Test oversized payloads, malformed multipart uploads, invalid UUIDs, invalid enums/profiles, and missing fields
- Confirm clean `4xx` behavior and correlation IDs in errors
- Verify request-size limit behavior in runtime
- No malformed input path returns unexpected `5xx`

## 5. Ingestion And Voice Runtime Validation

Status: `completed locally`

- Validate inline text ingestion end to end
- Validate supported file ingestion paths end to end
- Validate audio/voice flows, transcription behavior, and TTS fallback
- Test corrupted/invalid file handling
- Confirm ingestion/job status transitions are correct

## 6. Retrieval And Chat Runtime Validation

Status: `completed locally`

- Validate retrieval, citations, reranking, no-source behavior, and conversation continuation
- Confirm access boundaries are preserved in retrieved content
- Confirm older valid conversations still work
- Confirm missing/inaccessible conversations return correct errors

## 7. Resilience Drills

Status: `partially completed`

- Test Redis unavailable behavior
- Test DB unavailable/transient failure behavior
- Test storage failure behavior
- Test provider timeout/unavailable behavior
- Test worker/job failure and retry behavior if applicable
- Record observed fallback, retry, and error behavior

## 8. Load And Scale Validation

Status: `partially completed`

- Run a real load harness for chat, ingestion, and mixed traffic
- Capture `p50` / `p95` / `p99` latency
- Capture DB pressure, queue behavior, and error rate
- Identify bottlenecks with evidence, not guesses
- Define acceptable thresholds for `GO`

## 9. Observability Validation

Status: `partially completed`

- Verify logs, metrics, correlation IDs, and health/readiness signals under normal and failure conditions
- Confirm denied access, provider failures, and rate-limit events are diagnosable
- Validate tracing if enabled in the target environment
- Ensure incident debugging signals are sufficient

## 10. Final GO Criteria

Status: `not yet met`

- All critical/high issues are fixed or explicitly accepted
- DB-backed integration tests pass
- Live migrations pass
- No unexpected `5xx` in auth/validation/abuse paths
- Resilience drills complete with acceptable behavior
- Load results meet agreed thresholds
- Observability is adequate for support/on-call
- Final readiness report is updated with:
  - validated areas
  - remaining risks
  - blockers removed
  - severity-ranked findings
  - explicit `GO` or `NO-GO`
