from uuid import uuid4

import pytest

from app.core.config import Settings
from app.domain.entities.rag import Principal
from app.domain.errors import TooManyRequestsError
from app.security.rate_limit import RateLimiter


def test_rate_limiter_blocks_after_limit():
    settings = Settings(
        _env_file=None,
        redis_url="redis://localhost:1/0",
        rate_limit_window_seconds=60,
        rate_limit_requests_per_window=1,
    )
    limiter = RateLimiter(settings)
    limiter._redis = None
    principal = Principal(user_id=uuid4(), email=None, auth_method="jwt")

    import asyncio

    asyncio.run(limiter.check_request(principal=principal, tenant_id="tenant", route_key="/v1/tenants"))
    with pytest.raises(TooManyRequestsError):
        asyncio.run(limiter.check_request(principal=principal, tenant_id="tenant", route_key="/v1/tenants"))
