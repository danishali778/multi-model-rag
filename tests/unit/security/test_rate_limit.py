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

    asyncio.run(limiter.check_request(principal=principal, workspace_id="workspace", route_key="/v1/chat"))
    with pytest.raises(TooManyRequestsError):
        asyncio.run(limiter.check_request(principal=principal, workspace_id="workspace", route_key="/v1/chat"))


def test_rate_limiter_uses_chat_limit_for_balanced_profile():
    settings = Settings(
        _env_file=None,
        redis_url="redis://localhost:1/0",
        rate_limit_window_seconds=60,
        rate_limit_requests_per_window=5,
        rate_limit_chat_requests_per_window=2,
        rate_limit_reasoning_requests_per_window=1,
    )
    limiter = RateLimiter(settings)
    limiter._redis = None
    principal = Principal(user_id=uuid4(), email=None, auth_method="jwt")

    import asyncio

    asyncio.run(
        limiter.check_request(
            principal=principal,
            workspace_id="workspace",
            route_key="/v1/chat",
            profile="balanced",
        )
    )
    asyncio.run(
        limiter.check_request(
            principal=principal,
            workspace_id="workspace",
            route_key="/v1/chat",
            profile="balanced",
        )
    )
    with pytest.raises(TooManyRequestsError):
        asyncio.run(
            limiter.check_request(
                principal=principal,
                workspace_id="workspace",
                route_key="/v1/chat",
                profile="balanced",
            )
        )


def test_rate_limiter_uses_reasoning_limit_for_reasoning_profile():
    settings = Settings(
        _env_file=None,
        redis_url="redis://localhost:1/0",
        rate_limit_window_seconds=60,
        rate_limit_requests_per_window=5,
        rate_limit_chat_requests_per_window=2,
        rate_limit_reasoning_requests_per_window=1,
    )
    limiter = RateLimiter(settings)
    limiter._redis = None
    principal = Principal(user_id=uuid4(), email=None, auth_method="jwt")

    import asyncio

    asyncio.run(
        limiter.check_request(
            principal=principal,
            workspace_id="workspace",
            route_key="/v1/chat",
            profile="reasoning",
        )
    )
    with pytest.raises(TooManyRequestsError):
        asyncio.run(
            limiter.check_request(
                principal=principal,
                workspace_id="workspace",
                route_key="/v1/chat",
                profile="reasoning",
            )
        )


def test_rate_limiter_memory_fallback_enforces_limit_under_concurrency():
    settings = Settings(
        _env_file=None,
        redis_url="redis://localhost:1/0",
        rate_limit_window_seconds=60,
        rate_limit_requests_per_window=2,
    )
    limiter = RateLimiter(settings)
    limiter._redis = None
    principal = Principal(user_id=uuid4(), email=None, auth_method="jwt")

    import asyncio

    async def _attempt() -> bool:
        try:
            await limiter.check_request(
                principal=principal,
                workspace_id="workspace",
                route_key="/v1/documents",
            )
        except TooManyRequestsError:
            return False
        return True

    async def _run_attempts() -> list[bool]:
        return await asyncio.gather(_attempt(), _attempt(), _attempt())

    allowed = asyncio.run(_run_attempts())

    assert sum(allowed) == 2
    assert allowed.count(False) == 1
