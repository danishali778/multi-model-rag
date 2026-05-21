import asyncio
from uuid import uuid4

import httpx

from app.api.schemas.documents import CreateUploadUrlResponse
from app.core.config import Settings
from app.storage.object_store import StorageClient


def test_create_signed_upload_target_builds_absolute_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    settings = Settings(_env_file=None)
    client = StorageClient(settings)

    async def fake_request(method: str, path: str, **kwargs):
        return httpx.Response(
            200,
            json={"signedUrl": "/storage/v1/object/upload/sign/raw-documents/path?token=abc", "token": "abc"},
        )

    client._request = fake_request  # type: ignore[method-assign]
    target = asyncio.run(client.create_signed_upload_target(bucket="raw-documents", path="path"))

    assert target.bucket == "raw-documents"
    assert target.path == "path"
    assert target.upload_url == "https://example.supabase.co/storage/v1/object/upload/sign/raw-documents/path?token=abc"


def test_create_signed_upload_target_normalizes_relative_upload_path(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    settings = Settings(_env_file=None)
    client = StorageClient(settings)

    async def fake_request(method: str, path: str, **kwargs):
        return httpx.Response(
            200,
            json={"signedUrl": "/object/upload/sign/raw-documents/path?token=abc", "token": "abc"},
        )

    client._request = fake_request  # type: ignore[method-assign]
    target = asyncio.run(client.create_signed_upload_target(bucket="raw-documents", path="path"))

    assert target.upload_url == "https://example.supabase.co/storage/v1/object/upload/sign/raw-documents/path?token=abc"


def test_create_signed_upload_target_normalizes_absolute_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    settings = Settings(_env_file=None)
    client = StorageClient(settings)

    async def fake_request(method: str, path: str, **kwargs):
        return httpx.Response(
            200,
            json={"signedUrl": "https://example.supabase.co/object/upload/sign/raw-documents/path?token=abc", "token": "abc"},
        )

    client._request = fake_request  # type: ignore[method-assign]
    target = asyncio.run(client.create_signed_upload_target(bucket="raw-documents", path="path"))

    assert target.upload_url == "https://example.supabase.co/storage/v1/object/upload/sign/raw-documents/path?token=abc"


def test_create_upload_url_response_normalizes_absolute_signed_url():
    response = CreateUploadUrlResponse(
        bucket="raw-documents",
        path="path",
        upload_url="https://example.supabase.co/object/upload/sign/raw-documents/path?token=abc",
        document_id=uuid4(),
    )

    assert response.upload_url == "https://example.supabase.co/storage/v1/object/upload/sign/raw-documents/path?token=abc"
