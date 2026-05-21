from __future__ import annotations

from types import SimpleNamespace


class FakeStorageClient:
    async def create_signed_upload_target(self, *, bucket: str, path: str, upsert: bool = False):
        return SimpleNamespace(bucket=bucket, path=path, upload_url="https://example/upload")
