from __future__ import annotations

import asyncio
import sys
import warnings


def configure_asyncio_runtime() -> None:
    if sys.platform != "win32":
        return
    # Psycopg async connections still require the selector policy on Windows,
    # but the policy APIs themselves are deprecated on newer Python versions.
    # Keep the compatibility shim isolated here so the rest of the app can stay
    # on normal asyncio primitives.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if policy_cls is None:
            return
        current_policy = asyncio.get_event_loop_policy()
        if not isinstance(current_policy, policy_cls):
            asyncio.set_event_loop_policy(policy_cls())
