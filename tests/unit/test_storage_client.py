import asyncio

import httpx

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
    assert target.upload_url.startswith("https://example.supabase.co/")
