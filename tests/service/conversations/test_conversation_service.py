import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.entities.rag import Principal
from app.domain.errors import NotFoundError
from app.services.conversation_service import ConversationService


class _Repository:
    def __init__(self, *, conversation=None, rows=None):
        self._conversation = conversation
        self._rows = rows or []

    async def get_conversation(self, *, workspace_id, conversation_id, user_id):
        return self._conversation

    async def list_conversation_messages(self, *, workspace_id, conversation_id, user_id):
        return list(self._rows)


def test_get_conversation_messages_returns_messages_for_owned_conversation():
    conversation_id = uuid4()
    now = datetime.now(UTC)
    service = ConversationService(
        _Repository(
            conversation=SimpleNamespace(id=conversation_id),
            rows=[
                SimpleNamespace(
                    id=uuid4(),
                    role="assistant",
                    content="Remote work is allowed.",
                    model_profile="balanced",
                    sources=[],
                    token_usage={},
                    created_at=now,
                )
            ],
        )
    )

    response = asyncio.run(
        service.get_conversation_messages(
            workspace_id=uuid4(),
            conversation_id=conversation_id,
            principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key"),
        )
    )

    assert response.conversation_id == conversation_id
    assert response.items[0].content == "Remote work is allowed."


def test_get_conversation_messages_raises_not_found_for_missing_conversation():
    service = ConversationService(_Repository(conversation=None))

    with pytest.raises(NotFoundError, match="Conversation not found"):
        asyncio.run(
            service.get_conversation_messages(
                workspace_id=uuid4(),
                conversation_id=uuid4(),
                principal=Principal(user_id=uuid4(), email="dev@example.com", auth_method="api_key"),
            )
        )
