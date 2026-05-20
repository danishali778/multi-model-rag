from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.api.schemas.chat import ChatRequest, ChatResponse, SourceResponse, UsageResponse
from app.domain.entities.rag import Principal, RetrievalRequest, SourceCitation, UsageStats
from app.domain.errors import NotFoundError
from app.llm.prompts import build_messages
from app.storage.models.conversation import ConversationCreateInput, MessageCreateInput


@dataclass(slots=True)
class ChatTurnResult:
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    answer: str
    sources: list[SourceCitation]
    model: str
    usage: UsageStats
    metadata: dict


class ChatService:
    def __init__(
        self,
        *,
        conversation_repository,
        model_router,
        retrieval_service,
        security_policy,
        telemetry,
        settings,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._model_router = model_router
        self._retrieval_service = retrieval_service
        self._security_policy = security_policy
        self._telemetry = telemetry
        self._settings = settings

    async def answer_question(
        self,
        *,
        workspace_id: UUID,
        principal: Principal,
        payload: ChatRequest,
    ) -> ChatResponse:
        result = await self.answer_text_turn(
            workspace_id=workspace_id,
            principal=principal,
            query=payload.query,
            conversation_id=payload.conversation_id,
            profile=payload.profile or "balanced",
            document_ids=payload.document_ids,
        )
        return ChatResponse(
            conversation_id=result.conversation_id,
            message_id=result.assistant_message_id,
            answer=result.answer,
            sources=[_source_response(source) for source in result.sources],
            model=result.model,
            usage=UsageResponse(
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                total_tokens=result.usage.input_tokens + result.usage.output_tokens,
            ),
            metadata=result.metadata,
        )

    async def answer_text_turn(
        self,
        *,
        workspace_id: UUID,
        principal: Principal,
        query: str,
        conversation_id: UUID | None,
        profile: str,
        document_ids: list[UUID] | None = None,
    ) -> ChatTurnResult:
        decision = await self._retrieval_service.retrieve(
            RetrievalRequest(
                workspace_id=workspace_id,
                user_id=principal.user_id,
                question=query,
                filters=_retrieval_filters(document_ids),
                requested_top_k=getattr(self._settings, "max_context_chunks", 8),
                model_profile=profile,
                sensitivity_ceiling=getattr(self._settings, "retrieval_sensitivity_ceiling", None),
            )
        )
        self._security_policy.enforce_chat_sensitivity_policy(
            model_profile=profile,
            selected_sources=decision.selected_sources,
        )

        messages = build_messages(query, decision.context.source_blocks)
        completion = await self._model_router.complete_chat(messages, profile)
        sources = [
            SourceCitation(
                source_id=index,
                document_id=candidate.document_id,
                chunk_id=candidate.chunk_id,
                title=candidate.title,
                score=candidate.fused_score,
                snippet=candidate.content,
                section_title=candidate.section_title,
                subsection_title=candidate.subsection_title,
                section_path=list(candidate.section_path or []),
                page_number=candidate.page_number,
                chunk_type=candidate.chunk_type,
            )
            for index, candidate in enumerate(decision.selected_sources, start=1)
        ]
        usage = UsageStats(
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            estimated_cost_usd=completion.estimated_cost_usd,
        )

        if conversation_id is None:
            conversation_id = await self._conversation_repository.create_conversation(
                ConversationCreateInput(
                    workspace_id=workspace_id,
                    user_id=principal.user_id,
                    title=_conversation_title(query),
                )
            )
        else:
            await self._conversation_repository.list_conversation_messages(
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                user_id=principal.user_id,
            )
            conversation_rows = await self._conversation_repository.list_conversations(
                workspace_id=workspace_id,
                user_id=principal.user_id,
                limit=100,
            )
            if not any(row.id == conversation_id for row in conversation_rows):
                raise NotFoundError("Conversation not found.")

        user_message_id = await self._conversation_repository.create_message(
            MessageCreateInput(
                conversation_id=conversation_id,
                role="user",
                content=query,
                model_profile=profile,
                sources=[],
                token_usage={},
            )
        )
        message_id = await self._conversation_repository.create_message(
            MessageCreateInput(
                conversation_id=conversation_id,
                role="assistant",
                content=completion.answer,
                model_profile=profile,
                sources=[_source_payload(source) for source in sources],
                token_usage={
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.input_tokens + usage.output_tokens,
                    "estimated_cost_usd": usage.estimated_cost_usd,
                },
            )
        )

        return ChatTurnResult(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=message_id,
            answer=completion.answer,
            sources=sources,
            model=f"{completion.provider}:{completion.model_name}",
            usage=usage,
            metadata={
                "profile": profile,
                "retrieval_mode": decision.retrieval_mode,
                "rewrite_used": decision.rewrite_used,
                "reranker_used": decision.reranker_used,
                "candidate_counts": decision.candidate_counts,
                "no_source_reason": decision.no_source_reason,
            },
        )


def _source_payload(source: SourceCitation) -> dict:
    return {
        "source_id": source.source_id,
        "document_id": str(source.document_id),
        "chunk_id": str(source.chunk_id),
        "title": source.title,
        "score": source.score,
        "snippet": source.snippet,
        "section_title": source.section_title,
        "subsection_title": source.subsection_title,
        "section_path": list(source.section_path),
        "page_number": source.page_number,
        "chunk_type": source.chunk_type,
    }


def _source_response(source: SourceCitation) -> SourceResponse:
    return SourceResponse(
        chunk_id=source.chunk_id,
        document_id=source.document_id,
        document_name=source.title,
        snippet=source.snippet,
        score=source.score,
        section_title=source.section_title,
        subsection_title=source.subsection_title,
        section_path=list(source.section_path),
        page_number=source.page_number,
        chunk_type=source.chunk_type,
    )


def _conversation_title(query: str) -> str:
    trimmed = " ".join(query.split())
    return trimmed[:80] if len(trimmed) > 80 else trimmed


def _retrieval_filters(document_ids: list[UUID] | None) -> dict:
    if not document_ids:
        return {}
    return {"document_ids": [str(item) for item in document_ids]}
