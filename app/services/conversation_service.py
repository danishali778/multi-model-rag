from __future__ import annotations

from uuid import UUID

from app.api.schemas.conversations import (
    ConversationDetailResponse,
    ConversationListItem,
    ConversationListResponse,
    MessageListItem,
)
from app.domain.entities.rag import Principal
from app.storage.repositories.rag import RagRepository


class ConversationService:
    def __init__(self, repository: RagRepository):
        self.repository = repository

    async def list_conversations(self, *, tenant_id: UUID, principal: Principal, limit: int) -> ConversationListResponse:
        rows = await self.repository.list_conversations(tenant_id=tenant_id, user_id=principal.user_id, limit=limit)
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
        tenant_id: UUID,
        conversation_id: UUID,
        principal: Principal,
    ) -> ConversationDetailResponse:
        rows = await self.repository.list_conversation_messages(
            tenant_id=tenant_id,
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
