from app.core.telemetry import Telemetry
from app.core.config import Settings
from app.ingestion.registry import ParserRegistry
from app.llm.providers.anthropic import AnthropicChatProvider
from app.llm.providers.groq import GroqChatProvider
from app.llm.providers.huggingface import HuggingFaceEmbeddingProvider
from app.llm.providers.ollama import OllamaChatProvider
from app.llm.providers.openai import OpenAIChatProvider, OpenAIEmbeddingProvider
from app.llm.router import ModelRouter
from app.retrieval.reranker import CrossEncoderReranker, NoopReranker
from app.retrieval.retriever import RetrievalService
from app.security.auth import AuthService
from app.security.policy import SecurityPolicyService
from app.security.rate_limit import RateLimiter
from app.services.admin_service import AdminService
from app.services.auth_service import SupabaseAuthBrokerService
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.services.document_service import DocumentService
from app.services.evaluation_service import EvaluationService
from app.services.feedback_service import FeedbackService
from app.services.health_service import HealthService
from app.services.ingestion_service import IngestionService
from app.services.personal_workspace_service import PersonalWorkspaceService
from app.services.tenant_service import TenantService
from app.storage.db.session import Database
from app.storage.object_store import StorageClient
from app.storage.repositories.rag import RagRepository
from app.storage.repositories.workspace import WorkspaceRepository
from app.workers.tasks import IngestionTaskRunner


class AppContainer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings)
        self.repository = RagRepository(self.db, settings)
        self.workspace_repository = WorkspaceRepository(self.db, settings)
        self.storage = StorageClient(settings)
        self.parser_registry = ParserRegistry()
        self.task_runner = IngestionTaskRunner(settings)
        self.auth_service = AuthService(settings)
        self.supabase_auth_service = SupabaseAuthBrokerService(settings)
        self.personal_workspace_service = PersonalWorkspaceService(self.workspace_repository)
        self.telemetry = Telemetry(settings)
        self.rate_limiter = RateLimiter(settings)
        self.security_policy = SecurityPolicyService(settings)
        self.embedding_providers = {
            "huggingface": HuggingFaceEmbeddingProvider(settings),
            "openai": OpenAIEmbeddingProvider(settings),
        }
        self.chat_providers = {
            "groq": GroqChatProvider(settings),
            "openai": OpenAIChatProvider(settings),
            "anthropic": AnthropicChatProvider(settings),
            "ollama": OllamaChatProvider(settings),
        }
        self.model_router = ModelRouter(
            settings=settings,
            chat_providers=self.chat_providers,
            embedding_providers=self.embedding_providers,
            telemetry=self.telemetry,
        )
        self.reranker = CrossEncoderReranker(settings) if settings.reranker_enabled else NoopReranker()
        self.retrieval_service = RetrievalService(
            repository=self.repository,
            model_router=self.model_router,
            reranker=self.reranker,
            settings=settings,
        )
        self.tenant_service = TenantService(self.repository)
        self.ingestion_service = IngestionService(
            repository=self.repository,
            model_router=self.model_router,
            storage=self.storage,
            parser_registry=self.parser_registry,
            task_runner=self.task_runner,
            telemetry=self.telemetry,
            settings=settings,
        )
        self.document_service = DocumentService(
            repository=self.repository,
            ingestion_service=self.ingestion_service,
            storage=self.storage,
            settings=settings,
        )
        self.chat_service = ChatService(
            repository=self.repository,
            model_router=self.model_router,
            retrieval_service=self.retrieval_service,
            security_policy=self.security_policy,
            telemetry=self.telemetry,
            settings=settings,
        )
        self.feedback_service = FeedbackService(self.repository, self.telemetry)
        self.conversation_service = ConversationService(self.repository)
        self.admin_service = AdminService(self.repository, self.ingestion_service)
        self.evaluation_service = EvaluationService(repository=self.repository, settings=settings)
        self.health_service = HealthService(
            database=self.db,
            model_router=self.model_router,
            telemetry=self.telemetry,
            settings=settings,
        )

    async def startup(self) -> None:
        self.settings.validate_phase1()
        self.telemetry.setup()
        await self.db.startup()

    async def shutdown(self) -> None:
        await self.db.shutdown()
