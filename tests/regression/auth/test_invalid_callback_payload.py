import asyncio

import pytest

from app.core.config import Settings
from app.domain.errors import BadRequestError
from app.services.auth_service import SupabaseAuthBrokerService


def test_finalize_callback_rejects_empty_payload():
    service = SupabaseAuthBrokerService(
        Settings(
            _env_file=None,
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_AUTH_PUBLIC_KEY="public-key",
            SUPABASE_SERVICE_ROLE_KEY="service-role",
        )
    )

    with pytest.raises(BadRequestError):
        asyncio.run(
            service.finalize_callback(
                token_hash=None,
                challenge_type=None,
                access_token=None,
                refresh_token=None,
            )
        )
