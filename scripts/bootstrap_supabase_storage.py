from __future__ import annotations

import json
import sys
from urllib import error, request


def ensure_bucket(api_url: str, headers: dict[str, str], bucket: str) -> None:
    payload = json.dumps(
        {
            "id": bucket,
            "name": bucket,
            "public": False,
            "file_size_limit": 52428800,
        }
    ).encode("utf-8")
    req = request.Request(
        f"{api_url.rstrip('/')}/storage/v1/bucket",
        data=payload,
        headers={**headers, "content-type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 409 or '"statusCode":"409"' in detail or '"error":"Duplicate"' in detail:
            return
        raise RuntimeError(f"bucket bootstrap failed for {bucket}: {exc.code} {detail}") from exc


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: python scripts/bootstrap_supabase_storage.py <api-url> <service-role-key> <bucket1,bucket2,...>")
        return 2

    api_url, service_role_key, bucket_csv = sys.argv[1], sys.argv[2], sys.argv[3]
    buckets = [item.strip() for item in bucket_csv.split(",") if item.strip()]
    headers = {
        "authorization": f"Bearer {service_role_key}",
        "apikey": service_role_key,
    }
    for bucket in buckets:
        ensure_bucket(api_url, headers, bucket)
    print({"buckets": buckets})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
