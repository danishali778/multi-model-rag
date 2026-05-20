from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.storage.db.session import Database
from app.storage.models.audit import AuditLogInput
from app.storage.models.connector_sync import ConnectorCheckpointUpsertInput
from app.storage.models.conversation import ConversationCreateInput, MessageCreateInput
from app.storage.models.document import (
    DocumentCreateInput,
    DocumentMetadataUpdateInput,
    DocumentStorageUpdateInput,
)
from app.storage.models.feedback import FeedbackCreateInput
from app.storage.models.ingestion import (
    ChunkReplacementInput,
    IngestionJobCreateInput,
    IngestionJobUpdateInput,
    StageExtractedDocumentInput,
)
from app.storage.models.usage import ModelUsageInput
from app.storage.models.workspace import PersonalWorkspaceCreateInput
from app.storage.repositories.audit import AuditRepository
from app.storage.repositories.connector_sync import ConnectorSyncRepository
from app.storage.repositories.conversation import ConversationRepository
from app.storage.repositories.document import DocumentRepository
from app.storage.repositories.feedback import FeedbackRepository
from app.storage.repositories.ingestion import IngestionRepository
from app.storage.repositories.retrieval import RetrievalRepository
from app.storage.repositories.usage import UsageRepository
from app.storage.repositories.workspace import WorkspaceRepository


class RagRepository:
    """Compatibility facade during the repository split."""

    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.workspace_repository = WorkspaceRepository(db, settings)
        self.document_repository = DocumentRepository(db, settings)
        self.ingestion_repository = IngestionRepository(db, settings)
        self.retrieval_repository = RetrievalRepository(db, settings)
        self.conversation_repository = ConversationRepository(db, settings)
        self.feedback_repository = FeedbackRepository(db, settings)
        self.audit_repository = AuditRepository(db, settings)
        self.usage_repository = UsageRepository(db, settings)
        self.connector_sync_repository = ConnectorSyncRepository(db, settings)

    async def list_workspaces_for_user(self, user_id: UUID):
        return await self.workspace_repository.list_workspaces_for_user(user_id)

    async def user_has_workspace_access(self, user_id: UUID, workspace_id: UUID) -> bool:
        return await self.workspace_repository.user_has_workspace_access(user_id, workspace_id)

    async def get_workspace_role(self, user_id: UUID, workspace_id: UUID) -> str | None:
        return await self.workspace_repository.get_workspace_role(user_id, workspace_id)

    async def get_primary_workspace_for_user(self, user_id: UUID):
        return await self.workspace_repository.get_primary_workspace_for_user(user_id)

    async def create_personal_workspace(self, *, user_id: UUID, email: str | None) -> UUID:
        return await self.workspace_repository.create_personal_workspace(
            PersonalWorkspaceCreateInput(user_id=user_id, email=email)
        )

    async def create_document(self, **payload: Any) -> UUID:
        return await self.document_repository.create_document(DocumentCreateInput(**payload))

    async def create_ingestion_job(self, *, workspace_id: UUID, document_id: UUID) -> UUID:
        return await self.ingestion_repository.create_ingestion_job(
            IngestionJobCreateInput(workspace_id=workspace_id, document_id=document_id)
        )

    async def update_job(
        self,
        job_id: UUID,
        *,
        status: str,
        stage: str,
        error_code: str | None = None,
        error_message: str | None = None,
        stats: dict[str, Any] | None = None,
        attempts: int | None = None,
    ) -> None:
        await self.ingestion_repository.update_job(
            job_id,
            IngestionJobUpdateInput(
                status=status,
                stage=stage,
                error_code=error_code,
                error_message=error_message,
                stats=stats or {},
                attempts=attempts,
            ),
        )

    async def update_document_status(self, document_id: UUID, status: str, *, content_hash: str | None) -> None:
        await self.document_repository.update_document_status(document_id, status, content_hash=content_hash)

    async def replace_document_chunks(
        self,
        *,
        workspace_id: UUID,
        document_id: UUID,
        blocks,
        chunks,
        embeddings,
        embedding_model: str,
        chunking_version: str,
    ) -> None:
        await self.ingestion_repository.replace_document_chunks(
            ChunkReplacementInput(
                workspace_id=workspace_id,
                document_id=document_id,
                blocks=blocks,
                chunks=chunks,
                embeddings=embeddings,
                embedding_model=embedding_model,
                chunking_version=chunking_version,
            )
        )

    async def list_documents(self, *, workspace_id: UUID, user_id: UUID, status: str | None, source_type: str | None, limit: int):
        return await self.document_repository.list_documents(
            workspace_id=workspace_id,
            user_id=user_id,
            status=status,
            source_type=source_type,
            limit=limit,
        )

    async def get_document(self, *, workspace_id: UUID, document_id: UUID, user_id: UUID):
        return await self.document_repository.get_document(
            workspace_id=workspace_id,
            document_id=document_id,
            user_id=user_id,
        )

    async def get_document_source(self, *, workspace_id: UUID, document_id: UUID, user_id: UUID):
        return await self.document_repository.get_document_source(
            workspace_id=workspace_id,
            document_id=document_id,
            user_id=user_id,
        )

    async def get_ingestion_job(self, *, workspace_id: UUID, job_id: UUID, user_id: UUID):
        return await self.ingestion_repository.get_ingestion_job(
            workspace_id=workspace_id,
            job_id=job_id,
            user_id=user_id,
        )

    async def get_ingestion_job_internal(self, *, workspace_id: UUID, job_id: UUID):
        return await self.ingestion_repository.get_ingestion_job_internal(workspace_id=workspace_id, job_id=job_id)

    async def get_document_for_ingestion(self, *, workspace_id: UUID, document_id: UUID):
        return await self.document_repository.get_document_for_ingestion(
            workspace_id=workspace_id,
            document_id=document_id,
        )

    async def update_document_storage(self, *, document_id: UUID, source_uri: str, storage_bucket: str, storage_path: str) -> None:
        await self.document_repository.update_document_storage(
            DocumentStorageUpdateInput(
                document_id=document_id,
                source_uri=source_uri,
                storage_bucket=storage_bucket,
                storage_path=storage_path,
            )
        )

    async def update_document_ingestion_metadata(
        self,
        document_id: UUID,
        *,
        metadata_updates: dict[str, Any],
        status: str | None = None,
    ) -> None:
        await self.document_repository.update_document_ingestion_metadata(
            DocumentMetadataUpdateInput(
                document_id=document_id,
                metadata_updates=metadata_updates,
                status=status,
            )
        )

    async def stage_extracted_document(
        self,
        *,
        document_id: UUID,
        content_hash: str,
        extracted_text: str,
        metadata: dict[str, Any],
        parser_version: str,
        processed_storage_bucket: str,
        processed_storage_path: str,
        should_skip: bool,
        chunking_version: str,
        embedding_model: str,
    ) -> None:
        await self.ingestion_repository.stage_extracted_document(
            StageExtractedDocumentInput(
                document_id=document_id,
                content_hash=content_hash,
                extracted_text=extracted_text,
                metadata=metadata,
                parser_version=parser_version,
                processed_storage_bucket=processed_storage_bucket,
                processed_storage_path=processed_storage_path,
                should_skip=should_skip,
                chunking_version=chunking_version,
                embedding_model=embedding_model,
            )
        )

    async def upsert_connector_checkpoint(
        self,
        *,
        workspace_id: UUID,
        connector_type: str,
        source_key: str,
        cursor: dict[str, Any],
        status: str,
        error_message: str | None = None,
    ) -> None:
        await self.connector_sync_repository.upsert_connector_checkpoint(
            ConnectorCheckpointUpsertInput(
                workspace_id=workspace_id,
                connector_type=connector_type,
                source_key=source_key,
                cursor=cursor,
                status=status,
                error_message=error_message,
            )
        )

    async def search_chunks(self, *, workspace_id: UUID, user_id: UUID, query_embedding: list[float], top_k: int, filters: dict[str, Any]):
        return await self.retrieval_repository.search_chunks(
            workspace_id=workspace_id,
            user_id=user_id,
            query_embedding=query_embedding,
            top_k=top_k,
            filters=filters,
        )

    async def search_vector_candidates(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any],
        sensitivity_ceiling: str | None,
    ):
        return await self.retrieval_repository.search_vector_candidates(
            workspace_id=workspace_id,
            user_id=user_id,
            query_embedding=query_embedding,
            limit=limit,
            filters=filters,
            sensitivity_ceiling=sensitivity_ceiling,
        )

    async def search_fts_candidates(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        query_text: str,
        limit: int,
        filters: dict[str, Any],
        sensitivity_ceiling: str | None,
    ):
        return await self.retrieval_repository.search_fts_candidates(
            workspace_id=workspace_id,
            user_id=user_id,
            query_text=query_text,
            limit=limit,
            filters=filters,
            sensitivity_ceiling=sensitivity_ceiling,
        )

    async def get_parent_context_chunks(self, parent_block_ids: list[UUID]):
        return await self.retrieval_repository.get_parent_context_chunks(parent_block_ids)

    async def diagnose_empty_retrieval(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        query_text: str,
        filters: dict[str, Any],
        sensitivity_ceiling: str | None,
    ) -> str:
        return await self.retrieval_repository.diagnose_empty_retrieval(
            workspace_id=workspace_id,
            user_id=user_id,
            query_text=query_text,
            filters=filters,
            sensitivity_ceiling=sensitivity_ceiling,
        )

    async def create_conversation(self, *, workspace_id: UUID, user_id: UUID, title: str) -> UUID:
        return await self.conversation_repository.create_conversation(
            ConversationCreateInput(workspace_id=workspace_id, user_id=user_id, title=title)
        )

    async def create_message(
        self,
        *,
        conversation_id: UUID,
        role: str,
        content: str,
        model_profile: str | None,
        sources: list[dict[str, Any]],
        token_usage: dict[str, Any],
    ) -> UUID:
        return await self.conversation_repository.create_message(
            MessageCreateInput(
                conversation_id=conversation_id,
                role=role,
                content=content,
                model_profile=model_profile,
                sources=sources,
                token_usage=token_usage,
            )
        )

    async def list_conversations(self, *, workspace_id: UUID, user_id: UUID, limit: int):
        return await self.conversation_repository.list_conversations(
            workspace_id=workspace_id,
            user_id=user_id,
            limit=limit,
        )

    async def list_conversation_messages(self, *, workspace_id: UUID, conversation_id: UUID, user_id: UUID):
        return await self.conversation_repository.list_conversation_messages(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    async def create_feedback(
        self,
        *,
        workspace_id: UUID,
        message_id: UUID,
        user_id: UUID,
        rating: str,
        comments: str | None,
        metadata: dict[str, Any],
    ) -> UUID:
        return await self.feedback_repository.create_feedback(
            FeedbackCreateInput(
                workspace_id=workspace_id,
                message_id=message_id,
                user_id=user_id,
                rating=rating,
                comments=comments,
                metadata=metadata,
            )
        )

    async def list_user_ingestion_jobs(self, *, workspace_id: UUID, user_id: UUID, limit: int):
        return await self.ingestion_repository.list_user_ingestion_jobs(
            workspace_id=workspace_id,
            user_id=user_id,
            limit=limit,
        )

    async def record_model_usage(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID | None,
        operation: str,
        model_profile: str,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_usd: float,
        details: dict[str, Any],
    ) -> None:
        await self.usage_repository.record_model_usage(
            ModelUsageInput(
                workspace_id=workspace_id,
                user_id=user_id,
                operation=operation,
                model_profile=model_profile,
                provider=provider,
                model_name=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated_cost_usd,
                details=details,
            )
        )

    async def record_audit_log(self, *, workspace_id: UUID, actor_id: UUID, event_type: str, details: dict[str, Any]) -> None:
        await self.audit_repository.record_audit_log(
            AuditLogInput(
                workspace_id=workspace_id,
                actor_id=actor_id,
                event_type=event_type,
                details=details,
            )
        )
