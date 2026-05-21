import pytest
from pydantic import ValidationError

from app.api.schemas.chat import ChatRequest


def test_legacy_chat_payload_shape_is_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(question="What is the policy?", model_profile="balanced")
