import asyncio
from datetime import datetime, UTC
from types import SimpleNamespace
from uuid import uuid4

from app.api.dependencies import WorkspaceContext
from app.api.routes.conversations import get_conversation_messages, list_conversations
from app.api.schemas.conversations import (
    ConversationDetailResponse,
    ConversationListItem,
    ConversationListResponse,
    MessageListItem,
)
from app.domain.entities.rag import Principal


def _context(conversation_service) -> WorkspaceContext:
    return WorkspaceContext(
        container=SimpleNamespace(conversation_service=conversation_service),
        principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key", role="owner"),
        workspace_id=uuid4(),
    )


def test_list_conversations_routes_limit_to_service():
    now = datetime.now(UTC)
    expected = ConversationListResponse(
        items=[ConversationListItem(id=uuid4(), title="Remote Work", created_at=now, updated_at=now)]
    )

    async def fake_list_conversations(*, workspace_id, principal, limit):
        assert limit == 15
        return expected

    response = asyncio.run(
        list_conversations(limit=15, context=_context(SimpleNamespace(list_conversations=fake_list_conversations)))
    )

    assert response == expected


def test_get_conversation_messages_routes_id_to_service():
    conversation_id = uuid4()
    expected = ConversationDetailResponse(
        conversation_id=conversation_id,
        items=[
            MessageListItem(
                id=uuid4(),
                role="assistant",
                content="Remote work is allowed.",
                created_at=datetime.now(UTC),
            )
        ],
    )

    async def fake_get_conversation_messages(**kwargs):
        assert kwargs["conversation_id"] == conversation_id
        return expected

    response = asyncio.run(
        get_conversation_messages(
            conversation_id,
            _context(SimpleNamespace(get_conversation_messages=fake_get_conversation_messages)),
        )
    )

    assert response == expected
