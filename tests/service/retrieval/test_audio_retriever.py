import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.core.config import Settings
from app.retrieval.audio_retriever import AudioRetrievalService
from app.storage.models.retrieval import RetrievalCandidateRow


class _Repo:
    async def search_vector_candidates(self, **kwargs):
        chunk_id = uuid4()
        self.prev_id = uuid4()
        self.next_id = uuid4()
        return [
            RetrievalCandidateRow(
                id=chunk_id,
                document_id=uuid4(),
                chunk_index=1,
                content="Deployment starts now.",
                metadata={"content_kind": "audio_transcript_segment", "start_ms": 1900, "end_ms": 4600},
                title="Daily Briefing",
                sensitivity="internal",
                previous_chunk_id=self.prev_id,
                next_chunk_id=self.next_id,
                chunking_version="hybrid-graph-v1",
            )
        ]

    async def search_fts_candidates(self, **kwargs):
        return []

    async def get_neighboring_chunks(self, **kwargs):
        document_id = uuid4()
        return [
            RetrievalCandidateRow(
                id=self.prev_id,
                document_id=document_id,
                chunk_index=0,
                content="Welcome everyone.",
                metadata={"content_kind": "audio_transcript_segment", "start_ms": 0, "end_ms": 1800},
                title="Daily Briefing",
                sensitivity="internal",
                chunking_version="hybrid-graph-v1",
            ),
            RetrievalCandidateRow(
                id=self.next_id,
                document_id=document_id,
                chunk_index=2,
                content="Rollback remains available.",
                metadata={"content_kind": "audio_transcript_segment", "start_ms": 4700, "end_ms": 6200},
                title="Daily Briefing",
                sensitivity="internal",
                chunking_version="hybrid-graph-v1",
            ),
        ]


def test_audio_retriever_expands_to_neighboring_transcript_chunks():
    async def _embed_texts(texts):
        return SimpleNamespace(vectors=[[0.1, 0.2]])

    service = AudioRetrievalService(
        retrieval_repository=_Repo(),
        model_router=SimpleNamespace(embed_texts=_embed_texts),
        settings=Settings(_env_file=None, supabase_db_url="postgresql://example", supabase_jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json", groq_api_key="groq", hf_api_token="hf", redis_url="redis://localhost:6379/0"),
    )

    async def _run():
        return await service.retrieve(
            workspace_id=uuid4(),
            user_id=uuid4(),
            query_text="When does deployment start?",
            top_k=2,
        )

    context = asyncio.run(_run())

    assert len(context.candidates) >= 2
    assert any(candidate.selection_role == "local_support" for candidate in context.candidates)
    assert any(candidate.metadata.get("start_ms") == 1900 for candidate in context.candidates)
