import psycopg
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.errors import ProviderUnavailableError
from app.llm.providers.base import ChatCompletion, EmbeddingResult
from app.main import create_app

DOC_PREFIX = "pytest-b2c-doc"
CHAT_PREFIX = "pytest-b2c-chat"


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

        document_response = client.post(
            "/v1/documents",
            headers=headers,
            json={
                "title": f"{DOC_PREFIX}-001",
                "source_type": "text",
                "text": "Remote work is allowed three days per week with manager approval.",
                "metadata": {"department": "hr"},
                "sensitivity": "internal"
            },
        )
        assert document_response.status_code == 200, document_response.text
        document_payload = document_response.json()
        document_id = document_payload["document_id"]
        job_id = document_payload["ingestion_job_id"]
        assert document_payload["status"] == "indexed"

        list_response = client.get("/v1/documents", headers=headers)
        assert list_response.status_code == 200
        assert any(item["id"] == document_id for item in list_response.json()["items"])

        detail_response = client.get(f"/v1/documents/{document_id}", headers=headers)
        assert detail_response.status_code == 200
        assert detail_response.json()["chunk_count"] >= 1

        jobs_response = client.get("/v1/ingestion-jobs", headers=headers)
        assert jobs_response.status_code == 200
        assert any(item["id"] == job_id for item in jobs_response.json()["items"])

        job_response = client.get(f"/v1/ingestion-jobs/{job_id}", headers=headers)
        assert job_response.status_code == 200
        assert job_response.json()["status"] == "succeeded"

        chat_response = client.post(
            "/v1/chat",
            headers=headers,
            json={
                "query": f"{CHAT_PREFIX}: What is the remote work policy?",
                "conversation_id": None,
                "profile": "balanced",
                "metadata": {"department": "hr"},
            },
        )
        assert chat_response.status_code == 200, chat_response.text
        chat_payload = chat_response.json()
        assert chat_payload["model"].startswith("groq:")
        assert chat_payload["sources"]
        assert "[source:1]" in chat_payload["answer"]

        conversations_response = client.get("/v1/conversations", headers=headers)
        assert conversations_response.status_code == 200
        assert conversations_response.json()["items"]

        conversation_messages = client.get(
            f"/v1/conversations/{chat_payload['conversation_id']}/messages",
            headers=headers,
        )
        assert conversation_messages.status_code == 200
        assert len(conversation_messages.json()["items"]) == 2

        feedback_response = client.post(
            f"/v1/messages/{chat_payload['message_id']}/feedback",
            headers=headers,
            json={
                "rating": 1,
                "comment": "Correct and useful.",
                "categories": ["helpful_sources"],
            },
        )
        assert feedback_response.status_code == 200, feedback_response.text
        assert feedback_response.json()["status"] == "recorded"

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
            "/v1/chat",
            headers={"X-API-Key": settings.api_key},
            json={
                "query": "What is the remote work policy?",
                "conversation_id": None,
                "profile": "balanced",
            },
        )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "provider_unavailable"


def test_chat_validation_rejects_legacy_payload_shape():
    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            headers={"X-API-Key": settings.api_key},
            json={
                "question": "What is the remote work policy?",
                "conversation_id": None,
                "model_profile": "balanced",
            },
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
