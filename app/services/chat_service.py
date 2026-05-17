import time
from dataclasses import asdict
from uuid import UUID

from app.api.schemas.chat import ChatRequest, ChatResponse, ModelResponse, SourceResponse, UsageResponse
from app.core.config import Settings
from app.domain.entities.rag import Principal, RetrievalRequest
from app.domain.errors import FeatureNotImplementedError
from app.llm.prompts import build_messages
from app.retrieval.filters import sanitize_metadata_filters
from app.retrieval.retriever import decision_to_metadata
from app.storage.repositories.rag import RagRepository


class ChatService:
    def __init__(self, *, repository: RagRepository, model_router, retrieval_service, security_policy, telemetry, settings: Settings):
        self.repository = repository
        self.model_router = model_router
        self.retrieval_service = retrieval_service
        self.security_policy = security_policy
        self.telemetry = telemetry
        self.settings = settings

    async def answer_question(
        self,
        tenant_id: UUID,
        principal: Principal,
        payload: ChatRequest,
    ) -> ChatResponse:
        if payload.stream:
            raise FeatureNotImplementedError(
                "Streaming chat is not implemented on this endpoint.",
                details={"supported": False, "endpoint": "/v1/tenants/{tenant_id}/chat"},
            )

        filters = sanitize_metadata_filters(payload.filters)
        retrieval_request = RetrievalRequest(
            tenant_id=tenant_id,
            user_id=principal.user_id,
            question=payload.question,
            filters=filters,
            requested_top_k=payload.top_k,
            model_profile=payload.model_profile,
            sensitivity_ceiling=self.settings.retrieval_sensitivity_ceiling,
        )
        retrieval_started = time.perf_counter()
        retrieval_decision = await self.retrieval_service.retrieve(retrieval_request)
        retrieval_seconds = time.perf_counter() - retrieval_started
        self.security_policy.enforce_chat_sensitivity_policy(
            model_profile=payload.model_profile,
            selected_sources=retrieval_decision.selected_sources,
        )
        source_blocks: list[str] = []
        sources: list[SourceResponse] = []
        for index, candidate in enumerate(retrieval_decision.selected_sources, start=1):
            snippet = candidate.content[:220].strip()
            source_blocks.append(retrieval_decision.context.source_blocks[index - 1])
            sources.append(
                SourceResponse(
                    source_id=index,
                    document_id=candidate.document_id,
                    chunk_id=candidate.chunk_id,
                    title=candidate.title,
                    score=float(candidate.fused_score),
                    snippet=snippet,
                )
            )
        generation_started = time.perf_counter()
        if source_blocks:
            completion = await self.model_router.complete_chat(
                build_messages(payload.question, source_blocks),
                payload.model_profile,
            )
            answer = completion.answer
        else:
            completion = await self.model_router.complete_chat(
                build_messages(
                    payload.question,
                    ["[source:0] No accessible sources were found for this user and tenant."],
                ),
                payload.model_profile,
            )
            answer = completion.answer
        generation_seconds = time.perf_counter() - generation_started
        conversation_id = payload.conversation_id or await self.repository.create_conversation(
            tenant_id=tenant_id,
            user_id=principal.user_id,
            title=payload.question[:80],
        )
        await self.repository.create_message(
            conversation_id=conversation_id,
            role="user",
            content=payload.question,
            model_profile=payload.model_profile,
            sources=[],
            token_usage={"retrieval": decision_to_metadata(retrieval_decision)},
        )
        assistant_message_id = await self.repository.create_message(
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            model_profile=payload.model_profile,
            sources=[source.model_dump(mode="json") for source in sources],
            token_usage={
                "input_tokens": completion.input_tokens,
                "output_tokens": completion.output_tokens,
                "estimated_cost_usd": completion.estimated_cost_usd,
                "attempt_count": completion.attempt_count,
                "retry_count": completion.retry_count,
                "fallback_used": completion.fallback_used,
                "attempts": [asdict(attempt) for attempt in completion.attempts],
                "retrieval": decision_to_metadata(retrieval_decision),
            },
        )
        if retrieval_decision.reranker_used and retrieval_decision.reranker_model:
            await self.repository.record_model_usage(
                tenant_id=tenant_id,
                user_id=principal.user_id,
                operation="rerank",
                model_profile=payload.model_profile,
                provider="local",
                model_name=retrieval_decision.reranker_model,
                input_tokens=len(retrieval_decision.selected_sources),
                output_tokens=0,
                estimated_cost_usd=0.0,
                details=decision_to_metadata(retrieval_decision),
            )
        await self.repository.record_model_usage(
            tenant_id=tenant_id,
            user_id=principal.user_id,
            operation="chat",
            model_profile=payload.model_profile,
            provider=completion.provider,
            model_name=completion.model_name,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            estimated_cost_usd=completion.estimated_cost_usd,
            details={
                "attempt_count": completion.attempt_count,
                "retry_count": completion.retry_count,
                "fallback_used": completion.fallback_used,
                "attempts": [asdict(attempt) for attempt in completion.attempts],
            },
        )
        retrieval_outcome = retrieval_decision.no_source_reason or "matched"
        self.telemetry.record_retrieval(
            outcome=retrieval_outcome,
            mode=retrieval_decision.retrieval_mode,
            duration_seconds=retrieval_seconds,
        )
        if completion.fallback_used:
            await self.repository.record_audit_log(
                tenant_id=tenant_id,
                actor_id=principal.user_id,
                event_type="chat.fallback_used",
                details={
                    "conversation_id": str(conversation_id),
                    "profile": payload.model_profile,
                    "provider": completion.provider,
                    "model_name": completion.model_name,
                    "attempts": [asdict(attempt) for attempt in completion.attempts],
                },
            )
        await self.repository.record_audit_log(
            tenant_id=tenant_id,
            actor_id=principal.user_id,
            event_type="chat.created",
            details={
                "conversation_id": str(conversation_id),
                "message_id": str(assistant_message_id),
                "source_count": len(sources),
                "auth_method": principal.auth_method,
                "fallback_used": completion.fallback_used,
                "provider": completion.provider,
                "model_name": completion.model_name,
                "retrieval": decision_to_metadata(retrieval_decision),
                "latency_ms": {
                    "retrieval": int(retrieval_seconds * 1000),
                    "generation": int(generation_seconds * 1000),
                },
            },
        )
        return ChatResponse(
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            answer=answer,
            model=ModelResponse(
                profile=payload.model_profile,
                provider=completion.provider,
                name=completion.model_name,
            ),
            sources=sources,
            usage=UsageResponse(
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                estimated_cost_usd=completion.estimated_cost_usd,
            ),
        )
