from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

try:
    from redis import asyncio as redis_asyncio
except ImportError:  # pragma: no cover - optional until deps installed
    redis_asyncio = None

from app.core.config import Settings
from app.domain.entities.rag import Principal
from app.domain.errors import TooManyRequestsError


@dataclass(slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RateLimiter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._memory_store: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._redis = (
            redis_asyncio.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
            if redis_asyncio
            else None
        )

    async def check_request(
        self,
        *,
        principal: Principal,
        tenant_id: str | None,
        route_key: str,
        profile: str | None = None,
    ) -> RateLimitDecision:
        limit = self._limit_for_profile(profile)
        key = f"ratelimit:{tenant_id or 'global'}:{principal.user_id}:{route_key}:{profile or 'default'}"
        decision = await self._check_window(key, limit, self.settings.rate_limit_window_seconds)
        if not decision.allowed:
            raise TooManyRequestsError(
                details={
                    "limit": limit,
                    "window_seconds": self.settings.rate_limit_window_seconds,
                    "retry_after_seconds": decision.retry_after_seconds,
                    "route_key": route_key,
                    "profile": profile,
                }
            )
        return decision

    async def _check_window(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        if self._redis is not None:
            try:
                return await self._check_window_redis(key, limit, window_seconds)
            except Exception:  # noqa: BLE001
                self._redis = None
        return await self._check_window_memory(key, limit, window_seconds)

    async def _check_window_redis(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = int(time.time())
        window_start = now - window_seconds
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, window_seconds)
            _, current_count, _, _ = await pipe.execute()
        remaining = max(limit - int(current_count) - 1, 0)
        allowed = int(current_count) < limit
        return RateLimitDecision(allowed=allowed, remaining=remaining, retry_after_seconds=window_seconds if not allowed else 0)

    async def _check_window_memory(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        async with self._lock:
            now = time.time()
            bucket = self._memory_store.setdefault(key, deque())
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(int(window_seconds - (now - bucket[0])), 1)
                return RateLimitDecision(allowed=False, remaining=0, retry_after_seconds=retry_after)
            bucket.append(now)
            return RateLimitDecision(allowed=True, remaining=max(limit - len(bucket), 0), retry_after_seconds=0)

    def _limit_for_profile(self, profile: str | None) -> int:
        if profile == "reasoning":
            return self.settings.rate_limit_reasoning_requests_per_window
        if profile in {"fast", "balanced", "local"}:
            return self.settings.rate_limit_chat_requests_per_window
        return self.settings.rate_limit_requests_per_window
