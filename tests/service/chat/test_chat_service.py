import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.schemas.chat import ChatRequest
from app.domain.entities.rag import (
    ContextAssemblyResult,
    Principal,
    RetrievalCandidate,
    RetrievalDecision,
)
from app.domain.errors import NotFoundError
from app.services.chat_service import ChatService


class _Repo:
    def __init__(self):
        self.created_conversation = None
        self.created_messages = []

    async def create_conversation(self, payload):
        self.created_conversation = payload
        return uuid4()

    async def create_message(self, payload):
        self.created_messages.append(payload)
        return uuid4()

    async def list_conversation_messages(self, *, workspace_id, conversation_id, user_id):
        return []

    async def list_conversations(self, *, workspace_id, user_id, limit):
        return []

    async def get_conversation(self, *, workspace_id, conversation_id, user_id):
        return None


class _Retrieval:
    async def retrieve(self, request):
        candidate = RetrievalCandidate(
            chunk_id=uuid4(),
            document_id=uuid4(),
            chunk_index=0,
            title="Handbook",
            content="Remote work is allowed three days per week.",
            metadata={},
            sensitivity="internal",
            section_title="Policy",
            subsection_title="Remote Work",
            section_path=["Policy", "Remote Work"],
            fused_score=0.8,
        )
        return RetrievalDecision(
            selected_sources=[candidate],
            context=ContextAssemblyResult(
                candidates=[candidate],
                source_blocks=["[source:1] Document: Handbook\n\nRemote work is allowed three days per week."],
                total_tokens=20,
                dropped_reasons=[],
            ),
            retrieval_mode="hybrid",
            rewrite_used=False,
            reranker_used=False,
            no_source_reason=None,
            candidate_counts={"vector": 1, "fts": 1, "selected": 1},
            retrieval_config_version="hybrid-v1",
        )


class _SecurityPolicy:
    def enforce_chat_sensitivity_policy(self, **kwargs):
        return None


async def _complete_chat(messages, profile):
    return SimpleNamespace(
        answer="Remote work is allowed three days per week [source:1].",
        provider="groq",
        model_name="mock-model",
        input_tokens=50,
        output_tokens=20,
        estimated_cost_usd=0.0,
    )


def test_answer_question_returns_current_chat_schema():
    repo = _Repo()
    service = ChatService(
        conversation_repository=repo,
        model_router=SimpleNamespace(complete_chat=_complete_chat),
        retrieval_service=_Retrieval(),
        security_policy=_SecurityPolicy(),
        telemetry=SimpleNamespace(),
        settings=SimpleNamespace(max_context_chunks=8, retrieval_sensitivity_ceiling=None),
    )
    principal = Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key")

    response = asyncio.run(
        service.answer_question(
            workspace_id=uuid4(),
            principal=principal,
            payload=ChatRequest(query="What is the remote work policy?", profile="balanced"),
        )
    )

    assert response.answer.endswith("[source:1].")
    assert response.model == "groq:mock-model"
    assert response.sources[0].document_name == "Handbook"
    assert len(repo.created_messages) == 2


def test_answer_text_turn_reuses_existing_owned_conversation():
    repo = _Repo()
    existing_conversation_id = uuid4()

    async def _get_conversation(**kwargs):
        return SimpleNamespace(id=existing_conversation_id)

    repo.get_conversation = _get_conversation
    service = ChatService(
        conversation_repository=repo,
        model_router=SimpleNamespace(complete_chat=_complete_chat),
        retrieval_service=_Retrieval(),
        security_policy=_SecurityPolicy(),
        telemetry=SimpleNamespace(),
        settings=SimpleNamespace(max_context_chunks=8, retrieval_sensitivity_ceiling=None),
    )
    principal = Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key")

    result = asyncio.run(
        service.answer_text_turn(
            workspace_id=uuid4(),
            principal=principal,
            query="What is the remote work policy?",
            conversation_id=existing_conversation_id,
            profile="balanced",
        )
    )

    assert result.conversation_id == existing_conversation_id
    assert repo.created_conversation is None
    assert len(repo.created_messages) == 2


def test_answer_text_turn_rejects_missing_conversation():
    repo = _Repo()
    service = ChatService(
        conversation_repository=repo,
        model_router=SimpleNamespace(complete_chat=_complete_chat),
        retrieval_service=_Retrieval(),
        security_policy=_SecurityPolicy(),
        telemetry=SimpleNamespace(),
        settings=SimpleNamespace(max_context_chunks=8, retrieval_sensitivity_ceiling=None),
    )
    principal = Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key")

    with pytest.raises(NotFoundError, match="Conversation not found"):
        asyncio.run(
            service.answer_text_turn(
                workspace_id=uuid4(),
                principal=principal,
                query="What is the remote work policy?",
                conversation_id=uuid4(),
                profile="balanced",
            )
        )
