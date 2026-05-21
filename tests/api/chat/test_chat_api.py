import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.api.dependencies import WorkspaceContext
from app.api.routes.chat import answer_question
from app.api.schemas.chat import ChatRequest, ChatResponse, SourceResponse, UsageResponse
from app.domain.entities.rag import Principal


def test_chat_route_delegates_to_chat_service():
    expected = ChatResponse(
        conversation_id=uuid4(),
        message_id=uuid4(),
        answer="Remote work is allowed [source:1].",
        sources=[
            SourceResponse(
                document_id=uuid4(),
                document_name="Handbook",
                snippet="Remote work is allowed.",
                chunk_id=uuid4(),
            )
        ],
        model="groq:mock-model",
        usage=UsageResponse(input_tokens=10, output_tokens=5, total_tokens=15),
        metadata={"profile": "balanced"},
    )

    async def fake_answer_question(*, workspace_id, principal, payload):
        assert payload.query == "What is the remote work policy?"
        return expected

    context = WorkspaceContext(
        container=SimpleNamespace(chat_service=SimpleNamespace(answer_question=fake_answer_question)),
        principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key", role="owner"),
        workspace_id=uuid4(),
    )

    response = asyncio.run(
        answer_question(ChatRequest(query="What is the remote work policy?", profile="balanced"), context)
    )

    assert response == expected
