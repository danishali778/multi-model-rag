from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.domain.entities.rag import UploadTarget
from app.domain.errors import BadRequestError, ProviderUnavailableError


class StorageClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def create_signed_upload_target(
        self,
        *,
        bucket: str,
        path: str,
        upsert: bool = False,
    ) -> UploadTarget:
        response = await self._request(
            "POST",
            f"/storage/v1/object/upload/sign/{bucket}/{path}",
            json={"upsert": upsert},
        )
        payload = response.json()
        signed_url = payload.get("signedURL") or payload.get("signedUrl") or payload.get("url")
        if not signed_url:
            raise ProviderUnavailableError("Supabase Storage did not return a signed upload URL.")
        if signed_url.startswith("http"):
            parsed = urlparse(signed_url)
            if parsed.path.startswith("/storage/v1/"):
                upload_url = signed_url
            else:
                upload_url = parsed._replace(path=f"/storage/v1{parsed.path}").geturl()
        else:
            base = urlparse(str(self.settings.supabase_storage_url))
            relative_path = signed_url if signed_url.startswith("/") else f"/{signed_url}"
            if relative_path.startswith("/object/upload/sign/"):
                relative_path = f"/storage/v1{relative_path}"
            upload_url = f"{base.scheme}://{base.netloc}{relative_path}"
        return UploadTarget(
            bucket=bucket,
            path=path,
            upload_url=upload_url,
            token=payload.get("token"),
        )

    async def download_bytes(self, *, bucket: str, path: str) -> bytes:
        response = await self._request(
            "GET",
            f"/storage/v1/object/authenticated/{bucket}/{path}",
            expect_json=False,
        )
        return response.content

    async def upload_processed_text(
        self,
        *,
        bucket: str,
        path: str,
        text: str,
        content_type: str = "text/plain",
    ) -> None:
        response = await self._request(
            "POST",
            f"/storage/v1/object/{bucket}/{path}",
            content=text.encode("utf-8"),
            headers={"content-type": content_type, "x-upsert": "true"},
        )
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                "Failed to store processed artifact in Supabase Storage.",
                details={"status_code": response.status_code, "body": response.text[:500]},
            )

    async def upload_to_signed_url(
        self,
        *,
        upload_url: str,
        raw_bytes: bytes,
        content_type: str,
    ) -> None:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.put(upload_url, content=raw_bytes, headers={"content-type": content_type})
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                "Failed to upload bytes to the signed Supabase Storage URL.",
                details={"status_code": response.status_code, "body": response.text[:500]},
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        expect_json: bool = True,
        **kwargs,
    ) -> httpx.Response:
        if not self.settings.supabase_storage_url or not self.settings.supabase_storage_service_key:
            raise BadRequestError("Supabase Storage is not configured.")
        base_headers = {
            "authorization": f"Bearer {self.settings.supabase_storage_service_key}",
            "apikey": self.settings.supabase_storage_service_key,
        }
        headers = {**base_headers, **kwargs.pop("headers", {})}
        url = f"{str(self.settings.supabase_storage_url).rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                "Supabase Storage request failed.",
                details={"status_code": response.status_code, "body": response.text[:500], "path": path},
            )
        if expect_json:
            response.json()
        return response
