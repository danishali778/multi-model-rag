from app.storage.repositories.retrieval import RetrievalRepository


class VectorStore:
    def __init__(self, repository: RetrievalRepository):
        self.repository = repository
