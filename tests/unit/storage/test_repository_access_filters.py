import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.storage.repositories.document import DocumentRepository
from app.storage.repositories.ingestion import IngestionRepository


class _CursorContext:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _ConnectionContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeCursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []
        self.executions = []

    async def execute(self, query, params=None):
        self.executions.append((query, params))

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return list(self.rows)


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return _CursorContext(self._cursor)

    async def commit(self):
        return None


class _FakeDatabase:
    def __init__(self, cursor):
        self.cursor = cursor

    def connection(self):
        return _ConnectionContext(_FakeConnection(self.cursor))


def test_document_repository_list_documents_filters_by_creator():
    cursor = _FakeCursor(rows=[])
    repo = DocumentRepository(_FakeDatabase(cursor), SimpleNamespace())
    workspace_id = uuid4()
    user_id = uuid4()

    asyncio.run(
        repo.list_documents(
            workspace_id=workspace_id,
            user_id=user_id,
            status=None,
            source_type=None,
            limit=20,
        )
    )

    _, params = cursor.executions[0]
    assert params[:2] == [workspace_id, user_id]


def test_document_repository_get_document_filters_by_creator():
    cursor = _FakeCursor(
        row={
            "id": uuid4(),
            "title": "Handbook",
            "source_type": "text",
            "status": "indexed",
            "metadata": {},
            "chunk_count": 1,
        }
    )
    repo = DocumentRepository(_FakeDatabase(cursor), SimpleNamespace())
    workspace_id = uuid4()
    document_id = uuid4()
    user_id = uuid4()

    asyncio.run(
        repo.get_document(
            workspace_id=workspace_id,
            document_id=document_id,
            user_id=user_id,
        )
    )

    _, params = cursor.executions[0]
    assert params == (workspace_id, document_id, user_id)


def test_document_repository_get_document_source_filters_by_creator():
    cursor = _FakeCursor(
        row={
            "id": uuid4(),
            "title": "Handbook",
            "source_type": "text",
            "sensitivity": "internal",
            "metadata": {},
        }
    )
    repo = DocumentRepository(_FakeDatabase(cursor), SimpleNamespace())
    workspace_id = uuid4()
    document_id = uuid4()
    user_id = uuid4()

    asyncio.run(
        repo.get_document_source(
            workspace_id=workspace_id,
            document_id=document_id,
            user_id=user_id,
        )
    )

    _, params = cursor.executions[0]
    assert params == (workspace_id, document_id, user_id)


def test_ingestion_repository_get_ingestion_job_filters_by_creator():
    cursor = _FakeCursor(
        row={
            "id": uuid4(),
            "workspace_id": uuid4(),
            "document_id": uuid4(),
            "status": "queued",
            "stage": "queued",
            "attempts": 1,
            "stats": {},
            "error_code": None,
            "error_message": None,
        }
    )
    repo = IngestionRepository(_FakeDatabase(cursor), SimpleNamespace())
    workspace_id = uuid4()
    job_id = uuid4()
    user_id = uuid4()

    asyncio.run(
        repo.get_ingestion_job(
            workspace_id=workspace_id,
            job_id=job_id,
            user_id=user_id,
        )
    )

    _, params = cursor.executions[0]
    assert params == (workspace_id, job_id, user_id)
