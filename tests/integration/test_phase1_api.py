import psycopg
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.errors import ProviderUnavailableError
from app.llm.providers.base import ChatCompletion, EmbeddingResult
from app.main import create_app

DEV_TENANT_ID = "11111111-1111-1111-1111-111111111111"
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"
DOC_PREFIX = "pytest-phase1-doc"
CHAT_PREFIX = "pytest-phase1-chat"


def _cleanup_phase1_artifacts() -> None:
    with psycopg.connect(settings.supabase_db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from messages where conversation_id in (select id from conversations where title like %s)",
                (f"{CHAT_PREFIX}%",),
            )
            cur.execute(
                "delete from conversations where title like %s",
                (f"{CHAT_PREFIX}%",),
            )
            cur.execute(
                "delete from document_acl_groups where document_id in (select id from documents where title like %s)",
                (f"{DOC_PREFIX}%",),
            )
            cur.execute(
                "delete from ingestion_jobs where document_id in (select id from documents where title like %s)",
                (f"{DOC_PREFIX}%",),
            )
            cur.execute(
                "delete from document_chunks where document_id in (select id from documents where title like %s)",
                (f"{DOC_PREFIX}%",),
            )
            cur.execute("delete from documents where title like %s", (f"{DOC_PREFIX}%",))


def test_phase1_api_flow(monkeypatch):
    app = create_app()

    async def fake_embed_texts(texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.01] * settings.embedding_dimension for _ in texts],
            model_name="mock-embedding",
            provider="huggingface",
            input_tokens=64,
            estimated_cost_usd=0.0,
        )

    async def fake_complete_chat(messages: list[dict[str, str]], profile: str) -> ChatCompletion:
        return ChatCompletion(
            answer="The handbook answer is available in the indexed context [source:1].",
            model_name="mock-groq",
            provider="groq",
            input_tokens=128,
            output_tokens=32,
            estimated_cost_usd=0.0,
        )

    _cleanup_phase1_artifacts()
    headers = {"X-API-Key": settings.api_key}

    with TestClient(app) as client:
        container = client.app.state.container
        monkeypatch.setattr(container.model_router, "embed_texts", fake_embed_texts)
        monkeypatch.setattr(container.model_router, "complete_chat", fake_complete_chat)

        tenants_response = client.get("/v1/tenants", headers=headers)
        assert tenants_response.status_code == 200
        assert any(item["id"] == DEV_TENANT_ID for item in tenants_response.json()["items"])

        document_response = client.post(
            f"/v1/tenants/{DEV_TENANT_ID}/documents",
            headers=headers,
            json={
                "title": f"{DOC_PREFIX}-001",
                "source_type": "text",
                "text": "Remote work is allowed three days per week with manager approval.",
                "metadata": {"department": "hr"},
                "sensitivity": "internal",
                "acl_group_ids": [],
            },
        )
        assert document_response.status_code == 200, document_response.text
        document_payload = document_response.json()
        document_id = document_payload["document_id"]
        job_id = document_payload["ingestion_job_id"]
        assert document_payload["status"] == "indexed"

        list_response = client.get(f"/v1/tenants/{DEV_TENANT_ID}/documents", headers=headers)
        assert list_response.status_code == 200
        assert any(item["id"] == document_id for item in list_response.json()["items"])

        detail_response = client.get(
            f"/v1/tenants/{DEV_TENANT_ID}/documents/{document_id}",
            headers=headers,
        )
        assert detail_response.status_code == 200
        assert detail_response.json()["chunk_count"] >= 1

        job_response = client.get(
            f"/v1/tenants/{DEV_TENANT_ID}/ingestion-jobs/{job_id}",
            headers=headers,
        )
        assert job_response.status_code == 200
        assert job_response.json()["status"] == "succeeded"

        chat_response = client.post(
            f"/v1/tenants/{DEV_TENANT_ID}/chat",
            headers=headers,
            json={
                "question": f"{CHAT_PREFIX}: What is the remote work policy?",
                "conversation_id": None,
                "model_profile": "balanced",
                "top_k": 5,
                "filters": {"department": "hr"},
                "stream": False,
            },
        )
        assert chat_response.status_code == 200, chat_response.text
        chat_payload = chat_response.json()
        assert chat_payload["model"]["provider"] == "groq"
        assert chat_payload["sources"]
        assert "[source:1]" in chat_payload["answer"]

        conversations_response = client.get(f"/v1/tenants/{DEV_TENANT_ID}/conversations", headers=headers)
        assert conversations_response.status_code == 200
        assert conversations_response.json()["items"]

        conversation_messages = client.get(
            f"/v1/tenants/{DEV_TENANT_ID}/conversations/{chat_payload['conversation_id']}/messages",
            headers=headers,
        )
        assert conversation_messages.status_code == 200
        assert len(conversation_messages.json()["items"]) == 2

        feedback_response = client.post(
            f"/v1/tenants/{DEV_TENANT_ID}/messages/{chat_payload['message_id']}/feedback",
            headers=headers,
            json={
                "rating": 1,
                "comment": "Correct and useful.",
                "categories": ["helpful_sources"],
            },
        )
        assert feedback_response.status_code == 200, feedback_response.text
        assert feedback_response.json()["status"] == "recorded"

        usage_response = client.get(
            f"/v1/tenants/{DEV_TENANT_ID}/admin/usage",
            headers=headers,
        )
        assert usage_response.status_code == 200, usage_response.text
        assert usage_response.json()["totals"]["requests"] >= 2

        audit_response = client.get(
            f"/v1/tenants/{DEV_TENANT_ID}/admin/audit-logs",
            headers=headers,
        )
        assert audit_response.status_code == 200
        assert audit_response.json()["items"]

        retrieval_metrics_response = client.get(
            f"/v1/tenants/{DEV_TENANT_ID}/admin/retrieval-metrics",
            headers=headers,
        )
        assert retrieval_metrics_response.status_code == 200

        feedback_admin_response = client.get(
            f"/v1/tenants/{DEV_TENANT_ID}/admin/feedback",
            headers=headers,
        )
        assert feedback_admin_response.status_code == 200
        assert feedback_admin_response.json()["items"]

        metrics_response = client.get("/metrics")
        assert metrics_response.status_code == 200
        assert b"rag_api_requests_total" in metrics_response.content

    _cleanup_phase1_artifacts()


def test_chat_provider_failure_returns_503(monkeypatch):
    app = create_app()

    async def failing_embed_texts(texts: list[str]) -> EmbeddingResult:
        raise ProviderUnavailableError("Embedding provider is unavailable.")

    with TestClient(app) as client:
        container = client.app.state.container
        monkeypatch.setattr(container.model_router, "embed_texts", failing_embed_texts)

        response = client.post(
            f"/v1/tenants/{DEV_TENANT_ID}/chat",
            headers={"X-API-Key": settings.api_key},
            json={
                "question": "What is the remote work policy?",
                "conversation_id": None,
                "model_profile": "balanced",
                "top_k": 5,
                "filters": {},
                "stream": False,
            },
        )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "provider_unavailable"


def test_chat_stream_flag_returns_501():
    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            f"/v1/tenants/{DEV_TENANT_ID}/chat",
            headers={"X-API-Key": settings.api_key},
            json={
                "question": "What is the remote work policy?",
                "conversation_id": None,
                "model_profile": "balanced",
                "top_k": 5,
                "filters": {},
                "stream": True,
            },
        )

    assert response.status_code == 501
    body = response.json()
    assert body["error"]["code"] == "not_implemented"
