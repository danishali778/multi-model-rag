from __future__ import annotations

from uuid import UUID

from app.api.schemas.conversations import (
    ConversationDetailResponse,
    ConversationListItem,
    ConversationListResponse,
    MessageListItem,
)
from app.domain.entities.rag import Principal
from app.domain.errors import NotFoundError
from app.storage.repositories.conversation import ConversationRepository


class ConversationService:
    def __init__(self, conversation_repository: ConversationRepository):
        self.conversation_repository = conversation_repository

    async def list_conversations(self, *, workspace_id: UUID, principal: Principal, limit: int) -> ConversationListResponse:
        rows = await self.conversation_repository.list_conversations(
            workspace_id=workspace_id,
            user_id=principal.user_id,
            limit=limit,
        )
        return ConversationListResponse(
            items=[
                ConversationListItem(
                    id=row.id,
                    title=row.title,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]
        )

    async def get_conversation_messages(
        self,
        *,
        workspace_id: UUID,
        conversation_id: UUID,
        principal: Principal,
    ) -> ConversationDetailResponse:
        conversation = await self.conversation_repository.get_conversation(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            user_id=principal.user_id,
        )
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        rows = await self.conversation_repository.list_conversation_messages(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            user_id=principal.user_id,
        )
        return ConversationDetailResponse(
            conversation_id=conversation_id,
            items=[
                MessageListItem(
                    id=row.id,
                    role=row.role,
                    content=row.content,
                    model_profile=row.model_profile,
                    sources=row.sources,
                    token_usage=row.token_usage,
                    created_at=row.created_at,
                )
                for row in rows
            ],
        )
