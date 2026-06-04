from __future__ import annotations

import asyncio
import sys


def configure_asyncio_runtime() -> None:
    if sys.platform != "win32":
        return
    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_cls is None:
        return
    current_policy = asyncio.get_event_loop_policy()
    if not isinstance(current_policy, policy_cls):
        asyncio.set_event_loop_policy(policy_cls())
