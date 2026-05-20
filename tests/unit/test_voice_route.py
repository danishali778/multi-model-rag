from uuid import UUID, uuid4

import pytest

from app.api.routes.voice import _parse_document_ids, _parse_metadata
from app.domain.errors import BadRequestError


def test_parse_metadata_accepts_json_object():
    metadata = _parse_metadata('{"channel":"web","client":"test"}')

    assert metadata == {"channel": "web", "client": "test"}


def test_parse_document_ids_accepts_uuid_array():
    value = str(uuid4())

    document_ids = _parse_document_ids(f'["{value}"]')

    assert document_ids == [UUID(value)]


def test_parse_document_ids_rejects_invalid_shape():
    with pytest.raises(BadRequestError):
        _parse_document_ids('{"document_id":"not-a-list"}')
