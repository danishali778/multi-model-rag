from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(slots=True)
class Principal:
    user_id: UUID
    email: str | None
    auth_method: str
    role: str | None = None
    is_service_account: bool = False
    claims: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SourceCitation:
    source_id: int
    document_id: UUID
    chunk_id: UUID
    title: str
    score: float
    snippet: str
    section_title: str | None = None
    subsection_title: str | None = None
    section_path: list[str] = field(default_factory=list)
    page_number: int | None = None
    chunk_type: str | None = None


@dataclass(slots=True)
class UsageStats:
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


@dataclass(slots=True)
class ModelChoice:
    profile: str
    provider: str
    name: str


@dataclass(slots=True)
class ChatResult:
    conversation_id: UUID
    message_id: UUID
    answer: str
    model: ModelChoice
    sources: list[SourceCitation]
    usage: UsageStats


@dataclass(slots=True)
class RetrievalRequest:
    workspace_id: UUID
    user_id: UUID
    question: str
    filters: dict[str, Any]
    requested_top_k: int
    model_profile: str
    sensitivity_ceiling: str | None = None


@dataclass(slots=True)
class RetrievalCandidate:
    chunk_id: UUID
    document_id: UUID
    chunk_index: int
    title: str
    content: str
    metadata: dict[str, Any]
    sensitivity: str
    parent_block_id: UUID | None = None
    page_number: int | None = None
    chunk_type: str | None = None
    section_title: str | None = None
    subsection_title: str | None = None
    section_path: list[str] = field(default_factory=list)
    parent_content: str | None = None
    vector_score: float | None = None
    fts_score: float | None = None
    fused_score: float = 0.0
    selection_role: str | None = None


@dataclass(slots=True)
class ContextAssemblyResult:
    candidates: list[RetrievalCandidate]
    source_blocks: list[str]
    total_tokens: int
    dropped_reasons: list[str]
    assembly_policy: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalDecision:
    selected_sources: list[RetrievalCandidate]
    context: ContextAssemblyResult
    retrieval_mode: str
    rewrite_used: bool
    reranker_used: bool
    no_source_reason: str | None
    candidate_counts: dict[str, int]
    retrieval_config_version: str
    reranker_model: str | None = None
    query_class: str = "fact"
    strategy_name: str = "hybrid"
    query_features: dict[str, Any] = field(default_factory=dict)
    rewritten_query: str | None = None


@dataclass(slots=True)
class UploadTarget:
    bucket: str
    path: str
    upload_url: str
    token: str | None = None


@dataclass(slots=True)
class ExtractedBlock:
    id: UUID
    block_type: str
    text: str
    page_number: int | None
    heading_level: int | None
    section_path: list[str]
    order_index: int
    parent_block_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedDocument:
    text: str
    detected_source_type: str
    title: str | None
    metadata: dict[str, Any]
    blocks: list[ExtractedBlock] = field(default_factory=list)
    section_tree: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class IngestionTaskPayload:
    workspace_id: UUID
    document_id: UUID
    job_id: UUID
    force_reindex: bool = False
    chunking_version: str | None = None
    embedding_model: str | None = None


@dataclass(slots=True)
class ConnectorCheckpoint:
    workspace_id: UUID
    connector_type: str
    source_key: str
    cursor: dict[str, Any]


@dataclass(slots=True)
class ConnectorSyncRequest:
    workspace_id: UUID
    connector_type: str
    source_key: str
    cursor: dict[str, Any] | None = None


@dataclass(slots=True)
class WorkspaceSummary:
    id: UUID
    name: str
    slug: str
    role: str


@dataclass(slots=True)
class DocumentRecord:
    id: UUID
    workspace_id: UUID
    title: str
    source_type: str
    status: str
    sensitivity: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    chunk_count: int = 0


@dataclass(slots=True)
class FeedbackRecord:
    id: UUID
    workspace_id: UUID
    message_id: UUID | None
    conversation_id: UUID | None
    user_id: UUID | None
    rating: str | None
    comments: str | None
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(slots=True)
class ConversationSummary:
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ConversationMessage:
    id: UUID
    role: str
    content: str
    model_profile: str | None
    sources: list[dict[str, Any]]
    token_usage: dict[str, Any]
    created_at: datetime


@dataclass(slots=True)
class UsageBucket:
    key: str
    requests: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


@dataclass(slots=True)
class UsageSummary:
    request_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    buckets: list[UsageBucket]


@dataclass(slots=True)
class AuditLogRecord:
    id: UUID
    event_type: str
    details: dict[str, Any]
    actor_id: UUID | None
    created_at: datetime


@dataclass(slots=True)
class RetrievalMetricsSummary:
    total_messages: int
    no_result_rate: float
    no_access_rate: float
    avg_selected_sources: float
    avg_context_tokens: float


@dataclass(slots=True)
class EvaluationDatasetItem:
    question: str
    expected_answer: str
    required_document_ids: list[str]
    acceptable_chunk_ids: list[str]
    difficulty: str
    workspace_id: str
    user_id: str
    filters: dict[str, Any] = field(default_factory=dict)
    expected_no_source_reason: str | None = None
    expected_section_path: list[str] = field(default_factory=list)
    expected_page_number: int | None = None
    expected_chunk_type: str | None = None
    bad_example_label: str | None = None


@dataclass(slots=True)
class EvaluationRunSummary:
    id: UUID
    workspace_id: UUID
    run_type: str
    model_profile: str
    metrics: dict[str, Any]
    created_at: datetime
