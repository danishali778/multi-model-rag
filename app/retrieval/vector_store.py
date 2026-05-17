from app.storage.repositories.rag import RagRepository


class VectorStore:
    def __init__(self, repository: RagRepository):
        self.repository = repository
